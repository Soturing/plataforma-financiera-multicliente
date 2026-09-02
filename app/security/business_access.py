from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from re import Pattern
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from starlette.routing import compile_path

from app.config import Settings, get_settings
from app.errors import DomainError
from app.security.api import bearer, get_security_context
from app.security.authorization import AuthorizationDecision, authorize
from app.security.data_plane import (
    AuthorizedDataPlane,
    DataPlaneAccess,
    DataPlaneError,
    build_data_plane_router,
)
from app.security.models import AuthorizationRequest, SecurityContext
from app.security.policy import PERMISSIONS


SECURED_BUSINESS_ROUTES = frozenset(
    {
        ("POST", "/api/v1/facturas"),
        ("POST", "/api/v1/facturas/{factura_id}/procesar-simulado"),
        ("GET", "/api/v1/revision/resumen"),
        ("GET", "/api/v1/revision"),
        ("GET", "/api/v1/facturas/{factura_id}"),
        ("GET", "/api/v1/facturas/{factura_id}/expediente"),
        ("GET", "/api/v1/facturas/{factura_id}/archivo"),
        ("GET", "/api/v1/catalogos"),
        ("GET", "/api/v1/documentos/buscar"),
        ("GET", "/api/v1/documentos/archivo"),
        ("POST", "/api/v1/facturas/{factura_id}/aprobar"),
        ("POST", "/api/v1/facturas/{factura_id}/corregir"),
        ("POST", "/api/v1/facturas/{factura_id}/editar"),
        ("POST", "/api/v1/facturas/{factura_id}/rechazar"),
    }
)


def _compile_secure_routes() -> tuple[tuple[str, Pattern[str]], ...]:
    return tuple(
        (method, compile_path(path)[0])
        for method, path in sorted(SECURED_BUSINESS_ROUTES)
    )


_SECURED_ROUTE_PATTERNS = _compile_secure_routes()


def is_secured_business_request(method: str, path: str) -> bool:
    normalized_method = method.upper()
    return any(
        route_method == normalized_method and pattern.fullmatch(path)
        for route_method, pattern in _SECURED_ROUTE_PATTERNS
    )


@dataclass
class BusinessDataAccess:
    connection: Connection
    action: str
    tenant_id: UUID | None
    branch_id: UUID | None
    upload_dir: Path
    security: SecurityContext | None = None
    authorized: AuthorizedDataPlane | None = None
    settings: Settings | None = None
    request: Request | None = None
    request_id: UUID | None = None

    @property
    def secure(self) -> bool:
        return self.security is not None

    def actor_reference(self, untrusted_value: str | None = None) -> str:
        if self.security is not None:
            return str(self.security.actor_id)
        value = (untrusted_value or "").strip()
        if not value:
            raise DomainError("Indique quién realiza la operación.", 422)
        return value

    def require_action(self, action: str, *, branch_id: UUID | None = None) -> AuthorizationDecision | None:
        if self.security is None:
            return None
        effective_branch_id = self.branch_id if branch_id is None else branch_id
        if (
            self.authorized is not None
            and action == self.action
            and effective_branch_id == self.branch_id
        ):
            return self.authorized.decision
        decision = authorize(
            self.security,
            AuthorizationRequest(
                action=action,
                tenant_id=self.tenant_id,
                branch_id=effective_branch_id,
            ),
        )
        if self.settings and self.request and self.request_id:
            try:
                _append_authorization_event(
                    self.settings,
                    actor=self.security,
                    decision=decision,
                    authorized=None,
                    request=self.request,
                    request_id=self.request_id,
                    result="EXITO" if decision.allowed else "RECHAZO",
                    reason_code=decision.code,
                    tenant_id=self.tenant_id,
                    branch_id=effective_branch_id,
                    action=action,
                )
            except (psycopg.Error, DataPlaneError):
                if decision.allowed:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={"code": "security_audit_unavailable"},
                    ) from None
        if not decision.allowed:
            _raise_authorization_error(decision.code, decision.policy)
        return decision

    def require_branch(self, branch_id: UUID) -> None:
        self.require_action(self.action, branch_id=branch_id)

    def branch_key(self, branch_id: UUID) -> str:
        row = self.connection.execute(
            "SELECT clave FROM catalog.sucursales WHERE id = %s AND activa",
            (branch_id,),
        ).fetchone()
        if row is None:
            raise DomainError("Sucursal no encontrada.", 404)
        self.require_branch(branch_id)
        return row["clave"]

    def require_branch_key(self, branch_key: str) -> UUID:
        row = self.connection.execute(
            "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa",
            (branch_key,),
        ).fetchone()
        if row is None:
            raise DomainError(f"No existe una sucursal activa con clave {branch_key}.", 422)
        self.require_branch(row["id"])
        return row["id"]

    def require_invoice_branch(self, invoice_id: UUID, *, target_branch_id: UUID | None = None) -> None:
        row = self.connection.execute(
            """
            SELECT f.sucursal_id, s.clave AS sucursal_clave
              FROM core.facturas f
              JOIN catalog.sucursales s ON s.id = f.sucursal_id
             WHERE f.id = %s
            """,
            (invoice_id,),
        ).fetchone()
        if row is None:
            raise DomainError("Factura no encontrada.", 404)
        if row["sucursal_clave"] != "POR-ASIGNAR":
            self.require_branch(row["sucursal_id"])
        if target_branch_id is not None:
            self.require_branch(target_branch_id)


def get_optional_business_security_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SecurityContext | None:
    if not settings.enforce_business_security:
        return None
    return get_security_context(credentials=credentials, settings=settings)


@lru_cache
def require_business_data_plane(
    action: str,
    access: DataPlaneAccess,
) -> Callable[..., Iterator[BusinessDataAccess]]:
    def dependency(
        request: Request,
        x_tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-Id")] = None,
        x_branch_id: Annotated[UUID | None, Header(alias="X-Branch-Id")] = None,
        x_request_id: Annotated[UUID | None, Header(alias="X-Request-Id")] = None,
        security_context: Annotated[
            SecurityContext | None, Depends(get_optional_business_security_context)
        ] = None,
        settings: Annotated[Settings, Depends(get_settings)] = None,
    ) -> Iterator[BusinessDataAccess]:
        if not settings.enforce_business_security:
            with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
                yield BusinessDataAccess(
                    connection=connection,
                    action=action,
                    tenant_id=None,
                    branch_id=None,
                    upload_dir=settings.upload_dir.resolve(),
                )
            return

        if security_context is None:
            raise HTTPException(status_code=401, detail="Autenticación requerida")

        request_id = x_request_id or uuid4()
        authorization_request = AuthorizationRequest(
            action=action,
            tenant_id=x_tenant_id,
            branch_id=x_branch_id,
        )
        try:
            router = build_data_plane_router(settings)
            with router.connect(security_context, authorization_request, access) as session:
                try:
                    _append_authorization_event(
                        settings,
                        actor=security_context,
                        decision=session.authorized.decision,
                        authorized=session.authorized,
                        request=request,
                        request_id=request_id,
                        result="EXITO",
                        reason_code="allowed",
                    )
                except (psycopg.Error, DataPlaneError):
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={"code": "security_audit_unavailable"},
                    ) from None
                yield BusinessDataAccess(
                    connection=session.connection,
                    action=action,
                    tenant_id=x_tenant_id,
                    branch_id=x_branch_id,
                    upload_dir=session.authorized.registration.upload_dir,
                    security=security_context,
                    authorized=session.authorized,
                    settings=settings,
                    request=request,
                    request_id=request_id,
                )
        except DataPlaneError as exc:
            try:
                _append_authorization_event(
                    settings,
                    actor=security_context,
                    decision=None,
                    authorized=None,
                    request=request,
                    request_id=request_id,
                    result="RECHAZO",
                    reason_code=exc.code,
                    tenant_id=x_tenant_id,
                    branch_id=x_branch_id,
                    action=action,
                )
            except (psycopg.Error, DataPlaneError):
                pass
            _raise_data_plane_error(exc)
    dependency.__name__ = f"require_{action.replace('.', '_')}_{access.value}"
    dependency.business_security_action = action
    dependency.business_data_plane_access = access
    return dependency


def _append_authorization_event(
    settings: Settings,
    *,
    actor: SecurityContext,
    request: Request,
    request_id: UUID,
    result: str,
    reason_code: str,
    decision: AuthorizationDecision | None,
    authorized: AuthorizedDataPlane | None,
    tenant_id: UUID | None = None,
    branch_id: UUID | None = None,
    action: str | None = None,
) -> None:
    if not settings.control_database_url:
        raise DataPlaneError("control_plane_unavailable", "El plano de control no está configurado")
    effective_action = authorized.action if authorized is not None else action
    if effective_action is None:
        raise DataPlaneError("unknown_action", "No se pudo identificar la acción")
    permission = PERMISSIONS[effective_action]
    effective_tenant = (
        authorized.registration.tenant_id if authorized is not None else tenant_id
    )
    effective_branch = authorized.control_branch_id if authorized is not None else None
    effective_decision = decision
    with psycopg.connect(settings.control_database_url, row_factory=dict_row) as connection:
        if effective_branch is None and effective_tenant is not None and branch_id is not None:
            branch = connection.execute(
                """
                SELECT id
                  FROM control.branches
                 WHERE tenant_id = %s AND data_plane_branch_id = %s AND active
                """,
                (effective_tenant, branch_id),
            ).fetchone()
            effective_branch = branch["id"] if branch is not None else None
        connection.execute(
            """
            SELECT security_audit.append_event(
                'BUSINESS_AUTHORIZATION', %s, %s, %s, %s, %s, %s, %s,
                %s, 'http_route', %s, %s, %s, %s, %s, NULL, NULL, NULL,
                'ALTA', %s, %s
            )
            """,
            (
                result,
                actor.actor_id,
                actor.actor_type.value,
                (
                    effective_decision.effective_role.value
                    if effective_decision and effective_decision.effective_role
                    else None
                ),
                effective_tenant,
                permission.module.value,
                effective_branch,
                effective_action,
                request.url.path,
                actor.session_id,
                actor.auth_level.value,
                reason_code,
                request_id,
                effective_decision.policy if effective_decision else "authorization-v1",
                Jsonb(
                    {
                        "method": request.method,
                        "data_plane_branch_id": (
                            str(branch_id or authorized.branch_id)
                            if branch_id or (authorized and authorized.branch_id)
                            else None
                        ),
                    }
                ),
            ),
        )


def _raise_authorization_error(code: str, policy: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "policy": policy},
    )


def _raise_data_plane_error(exc: DataPlaneError) -> None:
    if exc.code == "tenant_read_only":
        status_code = status.HTTP_409_CONFLICT
    elif exc.code in {
        "tenant_selection_required",
        "branch_selection_required",
        "branch_not_assigned",
        "branch_unavailable",
        "no_applicable_assignment",
        "module_not_assigned",
        "action_not_granted",
        "recent_authentication_required",
        "reauthentication_required",
        "phishing_resistant_authentication_required",
        "hardware_key_required",
    }:
        status_code = status.HTTP_403_FORBIDDEN
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(status_code=status_code, detail={"code": exc.code})
