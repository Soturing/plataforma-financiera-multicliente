from __future__ import annotations

import json
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Protocol
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.config import Settings
from app.security.authorization import AuthorizationDecision, authorize
from app.security.models import AuthorizationRequest, SecurityContext


REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
MAX_CONFIG_BYTES = 64 * 1024
EXPECTED_CONFIG_FIELDS = frozenset({"tenant_id", "database_url", "upload_dir"})


class DataPlaneAccess(str, Enum):
    READ = "read"
    WRITE = "write"


class DataPlaneError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DataPlaneRegistration:
    tenant_id: UUID
    reference: str
    database_url: str = field(repr=False)
    upload_dir: Path = field(repr=False)


@dataclass(frozen=True)
class AuthorizedDataPlane:
    registration: DataPlaneRegistration
    decision: AuthorizationDecision
    action: str
    branch_id: UUID | None
    control_branch_id: UUID | None = None


@dataclass
class DataPlaneSession:
    connection: Connection
    authorized: AuthorizedDataPlane


class DataPlaneRegistry(Protocol):
    def load(self, reference: str) -> DataPlaneRegistration: ...


class FileDataPlaneRegistry:
    """Local registry adapter; production will replace it with a secret manager."""

    def __init__(self, config_dir: Path, *, require_tls: bool = False) -> None:
        self.config_dir = config_dir.resolve()
        self.require_tls = require_tls

    def load(self, reference: str) -> DataPlaneRegistration:
        if not REFERENCE_PATTERN.fullmatch(reference):
            raise DataPlaneError("invalid_data_plane_reference", "La referencia del data plane no es válida")
        if not self.config_dir.is_dir():
            raise DataPlaneError("data_plane_registry_unavailable", "El registro de data planes no está disponible")

        candidate = self.config_dir / f"{reference}.json"
        if candidate.is_symlink():
            raise DataPlaneError("unsafe_data_plane_config", "La configuración del data plane no es segura")
        try:
            resolved = candidate.resolve(strict=True)
            if resolved.parent != self.config_dir or not resolved.is_file():
                raise DataPlaneError("unsafe_data_plane_config", "La configuración del data plane no es segura")
            size = resolved.stat().st_size
            if size <= 0 or size > MAX_CONFIG_BYTES:
                raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida")
            with resolved.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except DataPlaneError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise DataPlaneError(
                "data_plane_registry_unavailable", "El registro de data planes no está disponible"
            ) from exc

        if not isinstance(payload, dict) or set(payload) != EXPECTED_CONFIG_FIELDS:
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida")
        try:
            tenant_id = UUID(str(payload["tenant_id"]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida") from exc

        database_url = payload["database_url"]
        if (
            not isinstance(database_url, str)
            or len(database_url) > 4096
            or not database_url.startswith(("postgresql://", "postgres://"))
        ):
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida")
        try:
            connection_options = conninfo_to_dict(database_url)
        except psycopg.ProgrammingError as exc:
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida") from exc
        if not connection_options.get("dbname") or not connection_options.get("user"):
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida")
        if self.require_tls and connection_options.get("sslmode") != "verify-full":
            raise DataPlaneError("data_plane_tls_required", "El data plane requiere TLS verificado")

        raw_upload_dir = payload["upload_dir"]
        if not isinstance(raw_upload_dir, str) or not raw_upload_dir.strip():
            raise DataPlaneError("invalid_data_plane_config", "La configuración del data plane no es válida")
        upload_dir = Path(raw_upload_dir)
        if not upload_dir.is_absolute():
            raise DataPlaneError("invalid_data_plane_config", "La raíz de archivos debe ser absoluta")

        return DataPlaneRegistration(
            tenant_id=tenant_id,
            reference=reference,
            database_url=database_url,
            upload_dir=upload_dir.resolve(),
        )


class TenantDataPlaneRouter:
    def __init__(
        self,
        control_database_url: str,
        registry: DataPlaneRegistry,
        *,
        connection_factory: Callable[..., Connection] = psycopg.connect,
    ) -> None:
        self.control_database_url = control_database_url
        self.registry = registry
        self.connection_factory = connection_factory

    def resolve(
        self,
        actor: SecurityContext,
        request: AuthorizationRequest,
        access: DataPlaneAccess,
        *,
        control_connection: Connection | None = None,
    ) -> AuthorizedDataPlane:
        decision = authorize(actor, request)
        if not decision.allowed:
            raise DataPlaneError(decision.code, "La política de autorización rechazó la operación")
        if request.tenant_id is None:
            raise DataPlaneError("tenant_selection_required", "Debe seleccionar un tenant")

        connection_context = (
            nullcontext(control_connection)
            if control_connection is not None
            else psycopg.connect(self.control_database_url, row_factory=dict_row)
        )
        with connection_context as conn:
            tenant = conn.execute(
                """
                SELECT state::text AS state, data_plane_reference
                  FROM control.tenants
                 WHERE id = %s
                """,
                (request.tenant_id,),
            ).fetchone()

            control_branch_id = None
            if request.branch_id is not None:
                branch = conn.execute(
                    """
                    SELECT id
                      FROM control.branches
                     WHERE tenant_id = %s
                       AND data_plane_branch_id = %s
                       AND active
                    """,
                    (request.tenant_id, request.branch_id),
                ).fetchone()
                if branch is None:
                    raise DataPlaneError(
                        "branch_unavailable", "La sucursal no pertenece al tenant autorizado"
                    )
                control_branch_id = branch["id"]

        if tenant is None or tenant["state"] not in {"ACTIVO", "SOLO_LECTURA"}:
            raise DataPlaneError("tenant_unavailable", "El tenant no está disponible")
        if access is DataPlaneAccess.WRITE and tenant["state"] != "ACTIVO":
            raise DataPlaneError("tenant_read_only", "El tenant está en modo de sólo lectura")
        reference = tenant["data_plane_reference"]
        if not reference:
            raise DataPlaneError("data_plane_not_configured", "El tenant no tiene data plane configurado")

        registration = self.registry.load(reference)
        if registration.reference != reference or registration.tenant_id != request.tenant_id:
            raise DataPlaneError(
                "data_plane_identity_mismatch", "La configuración no corresponde al tenant autorizado"
            )
        return AuthorizedDataPlane(
            registration=registration,
            decision=decision,
            action=request.action,
            branch_id=request.branch_id,
            control_branch_id=control_branch_id,
        )

    @contextmanager
    def connect(
        self,
        actor: SecurityContext,
        request: AuthorizationRequest,
        access: DataPlaneAccess,
        *,
        control_connection: Connection | None = None,
        data_connection: Connection | None = None,
    ) -> Iterator[DataPlaneSession]:
        authorized = self.resolve(
            actor,
            request,
            access,
            control_connection=control_connection,
        )
        owns_connection = data_connection is None
        if data_connection is not None:
            connection = data_connection
        else:
            try:
                connection = self.connection_factory(
                    authorized.registration.database_url,
                    row_factory=dict_row,
                )
            except psycopg.Error as exc:
                raise DataPlaneError("data_plane_unavailable", "No fue posible abrir el data plane") from exc

        try:
            connection_context = connection if owns_connection else nullcontext(connection)
            with connection_context:
                if access is DataPlaneAccess.READ:
                    connection.execute("SET TRANSACTION READ ONLY")
                try:
                    connection.execute(
                        "SELECT security_context.activate_request(%s, %s, %s, %s)",
                        (
                            authorized.registration.tenant_id,
                            actor.actor_id,
                            actor.session_id,
                            request.branch_id,
                        ),
                    )
                except psycopg.Error as exc:
                    raise DataPlaneError(
                        "data_plane_identity_rejected",
                        "El data plane rechazó la identidad del tenant",
                    ) from exc
                yield DataPlaneSession(connection=connection, authorized=authorized)
        finally:
            if owns_connection and not connection.closed:
                connection.close()


def build_data_plane_router(settings: Settings) -> TenantDataPlaneRouter:
    if not settings.control_database_url or settings.data_plane_config_dir is None:
        raise DataPlaneError(
            "data_plane_router_not_configured",
            "El router de data planes no está configurado",
        )
    non_production_environments = {"development", "test", "testing", "local"}
    require_tls = settings.environment.strip().lower() not in non_production_environments
    registry = FileDataPlaneRegistry(
        settings.data_plane_config_dir,
        require_tls=require_tls,
    )
    return TenantDataPlaneRouter(settings.control_database_url, registry)


def provision_data_plane_identity(
    database_url: str,
    tenant_id: UUID,
    *,
    connection: Connection | None = None,
) -> bool:
    """Binds an unprovisioned data plane once; an existing binding is immutable."""

    connection_context = (
        nullcontext(connection)
        if connection is not None
        else psycopg.connect(database_url, row_factory=dict_row)
    )
    with connection_context as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('security_context.tenant_identity'))")
        existing = conn.execute(
            "SELECT tenant_id FROM security_context.tenant_identity WHERE singleton FOR UPDATE"
        ).fetchone()
        if existing is not None:
            if existing["tenant_id"] != tenant_id:
                raise DataPlaneError(
                    "data_plane_already_bound",
                    "El data plane ya pertenece a otro tenant y no puede reasignarse",
                )
            conn.execute("SELECT security_context.finalize_tenant_isolation()")
            return False
        conn.execute(
            "INSERT INTO security_context.tenant_identity (singleton, tenant_id) VALUES (true, %s)",
            (tenant_id,),
        )
        conn.execute("SELECT security_context.finalize_tenant_isolation()")
        return True
