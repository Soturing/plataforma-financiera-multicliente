from __future__ import annotations

from functools import lru_cache
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.security.control_repository import ControlPlaneRepository, SecurityContextNotFound
from app.security.models import SecurityContext
from app.security.models import AuthorizationRequest
from app.security.authorization import AuthorizationDecision, authorize
from app.security.oidc import OIDCConfigurationError, OIDCVerificationError, OIDCVerifier


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
