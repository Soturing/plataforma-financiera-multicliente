from __future__ import annotations

from functools import lru_cache
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.security.control_repository import ControlPlaneRepository, SecurityContextNotFound
from app.security.lifecycle import IdentityLifecycleService, InvitationCommand, LifecycleError
from app.security.models import IdentityState, SecurityContext, SessionState
from app.security.models import AuthorizationRequest
from app.security.authorization import AuthorizationDecision, authorize
from app.security.oidc import OIDCConfigurationError, OIDCVerificationError, OIDCVerifier
from app.security.schemas import (
    InvitationCreatedResponse,
    InvitationCreateRequest,
    LifecycleActionResponse,
    RevokeSessionRequest,
    SuspendIdentityRequest,
)


router = APIRouter(prefix="/api/v1/security", tags=["seguridad"])
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthorizedContext:
    security: SecurityContext
    tenant_id: UUID | None
    branch_id: UUID | None
    decision: AuthorizationDecision


@lru_cache
def _security_services(
    control_database_url: str,
    identity_provider: str,
    issuer: str,
    audience: str,
    jwks_url: str,
    auth_level_claim: str | None,
) -> tuple[OIDCVerifier, ControlPlaneRepository]:
    verifier = OIDCVerifier(
        issuer=issuer,
        audience=audience,
        jwks_url=jwks_url,
        auth_level_claim=auth_level_claim,
    )
    repository = ControlPlaneRepository(control_database_url, identity_provider)
    return verifier, repository


@lru_cache
def _lifecycle_service(
    control_database_url: str, identity_provider: str
) -> IdentityLifecycleService:
    return IdentityLifecycleService(control_database_url, identity_provider)


def get_security_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> SecurityContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={"WWW-Authenticate": "Bearer"},
        )
    required = {
        "control_database_url": settings.control_database_url,
        "oidc_identity_provider": settings.oidc_identity_provider,
        "oidc_issuer": settings.oidc_issuer,
        "oidc_audience": settings.oidc_audience,
        "oidc_jwks_url": settings.oidc_jwks_url,
    }
    if any(not value for value in required.values()):
        raise HTTPException(status_code=503, detail="La autenticación segura no está configurada")
    try:
        verifier, repository = _security_services(
            settings.control_database_url,
            settings.oidc_identity_provider,
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_jwks_url,
            settings.oidc_auth_level_claim,
        )
        principal = verifier.verify(credentials.credentials)
        return repository.load_security_context(principal)
    except OIDCConfigurationError:
        raise HTTPException(status_code=503, detail="La autenticación segura no está disponible") from None
    except (OIDCVerificationError, SecurityContextNotFound):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial no válida",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_control_repository(settings: Settings = Depends(get_settings)) -> ControlPlaneRepository:
    required = {
        "control_database_url": settings.control_database_url,
        "oidc_identity_provider": settings.oidc_identity_provider,
        "oidc_issuer": settings.oidc_issuer,
        "oidc_audience": settings.oidc_audience,
        "oidc_jwks_url": settings.oidc_jwks_url,
    }
    if any(not value for value in required.values()):
        raise HTTPException(status_code=503, detail="La autenticación segura no está configurada")
    _, repository = _security_services(
        settings.control_database_url,
        settings.oidc_identity_provider,
        settings.oidc_issuer,
        settings.oidc_audience,
        settings.oidc_jwks_url,
        settings.oidc_auth_level_claim,
    )
    return repository


def require_permission(action: str) -> Callable[..., AuthorizedContext]:
    def dependency(
        x_tenant_id: UUID | None = Header(default=None, alias="X-Tenant-Id"),
        x_branch_id: UUID | None = Header(default=None, alias="X-Branch-Id"),
        context: SecurityContext = Depends(get_security_context),
    ) -> AuthorizedContext:
        decision = authorize(
            context,
            AuthorizationRequest(action=action, tenant_id=x_tenant_id, branch_id=x_branch_id),
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": decision.code, "policy": decision.policy},
            )
        return AuthorizedContext(context, x_tenant_id, x_branch_id, decision)

    return dependency


@router.get("/me")
def current_security_context(context: SecurityContext = Depends(get_security_context)):
    return {
        "actor_id": context.actor_id,
        "actor_type": context.actor_type,
        "session_id": context.session_id,
        "identity_state": context.identity_state,
        "session_state": context.session_state,
        "auth_level": context.auth_level,
        "assignments": [
            {
                "role": grant.role,
                "tenant_id": grant.tenant_id,
                "modules": sorted(module.value for module in grant.modules),
                "branch_ids": sorted(str(branch_id) for branch_id in grant.branch_ids),
                "conditional_permissions": sorted(grant.conditional_permissions),
                "all_modules": grant.all_modules,
                "all_branches": grant.all_branches,
                "state": grant.state,
                "valid_from": grant.valid_from,
                "valid_until": grant.valid_until,
            }
            for grant in context.grants
        ],
    }


@router.get("/scope-options")
def current_scope_options(
    context: SecurityContext = Depends(get_security_context),
    repository: ControlPlaneRepository = Depends(get_control_repository),
):
    """List only the control-plane labels that the authenticated actor may select."""
    if context.identity_state is not IdentityState.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "identity_not_active"},
        )
    if context.session_state is not SessionState.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "session_not_active"},
        )

    try:
        options = repository.load_scope_options(context)
    except SecurityContextNotFound:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credencial no válida",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    return {
        "actor": {
            "id": context.actor_id,
            "display_name": options.actor_display_name,
            "email": options.actor_email,
        },
        "session": {
            "id": context.session_id,
            "auth_level": context.auth_level,
            "authenticated_at": context.authenticated_at,
        },
        "tenants": [
            {
                "id": tenant.id,
                "slug": tenant.slug,
                "display_name": tenant.display_name,
                "state": tenant.state,
                "roles": tenant.roles,
                "modules": tenant.modules,
                "all_modules": tenant.all_modules,
                "all_branches": tenant.all_branches,
                "branches": [
                    {
                        "id": branch.id,
                        "code": branch.code,
                        "display_name": branch.display_name,
                    }
                    for branch in tenant.branches
                ],
            }
            for tenant in options.tenants
        ],
    }


@router.post(
    "/invitations",
    response_model=InvitationCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    payload: InvitationCreateRequest,
    response: Response,
    x_request_id: UUID | None = Header(default=None, alias="X-Request-Id"),
    context: SecurityContext = Depends(get_security_context),
    settings: Settings = Depends(get_settings),
):
    service = _configured_lifecycle_service(settings)
    try:
        created = service.create_invitation(
            context,
            InvitationCommand(
                email=payload.email,
                role=payload.role,
                tenant_id=payload.tenant_id,
                modules=frozenset(payload.modules),
                branch_ids=frozenset(payload.branch_ids),
                conditional_permissions=frozenset(payload.conditional_permissions),
                all_modules=payload.all_modules,
                all_branches=payload.all_branches,
                assignment_valid_until=payload.assignment_valid_until,
                reason=payload.reason,
            ),
            request_id=x_request_id,
        )
    except LifecycleError as exc:
        _raise_lifecycle_error(exc)
    response.headers["Cache-Control"] = "no-store"
    return {
        "invitation_id": created.invitation_id,
        "invitation_token": created.token,
        "expires_at": created.expires_at,
    }


@router.post(
    "/identities/{identity_id}/suspend",
    response_model=LifecycleActionResponse,
)
def suspend_identity(
    identity_id: UUID,
    payload: SuspendIdentityRequest,
    x_request_id: UUID | None = Header(default=None, alias="X-Request-Id"),
    context: SecurityContext = Depends(get_security_context),
    settings: Settings = Depends(get_settings),
):
    service = _configured_lifecycle_service(settings)
    try:
        service.suspend_identity(
            context, identity_id, payload.reason, request_id=x_request_id
        )
    except LifecycleError as exc:
        _raise_lifecycle_error(exc)
    return {"status": "ok"}


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=LifecycleActionResponse,
)
def revoke_session(
    session_id: UUID,
    payload: RevokeSessionRequest,
    x_request_id: UUID | None = Header(default=None, alias="X-Request-Id"),
    context: SecurityContext = Depends(get_security_context),
    settings: Settings = Depends(get_settings),
):
    service = _configured_lifecycle_service(settings)
    try:
        service.revoke_session(context, session_id, payload.reason, request_id=x_request_id)
    except LifecycleError as exc:
        _raise_lifecycle_error(exc)
    return {"status": "ok"}


def _configured_lifecycle_service(settings: Settings) -> IdentityLifecycleService:
    if not settings.control_database_url or not settings.oidc_identity_provider:
        raise HTTPException(status_code=503, detail="El plano de control no está configurado")
    return _lifecycle_service(settings.control_database_url, settings.oidc_identity_provider)


_AUTHORIZATION_ERRORS = {
    "identity_not_active",
    "session_not_active",
    "tenant_selection_required",
    "no_applicable_assignment",
    "module_not_assigned",
    "branch_selection_required",
    "branch_not_assigned",
    "action_not_granted",
    "recent_authentication_required",
    "reauthentication_required",
    "phishing_resistant_authentication_required",
    "hardware_key_required",
    "self_assignment_forbidden",
    "self_suspension_forbidden",
}


def _raise_lifecycle_error(exc: LifecycleError) -> None:
    if exc.code in _AUTHORIZATION_ERRORS:
        raise HTTPException(status_code=403, detail={"code": exc.code}) from None
    if exc.code in {"identity_not_found", "session_not_found"}:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from None
    raise HTTPException(status_code=422, detail={"code": exc.code}) from None
