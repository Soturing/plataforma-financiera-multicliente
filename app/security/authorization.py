from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone

from app.security.models import (
    AuthLevel,
    AuthorizationRequest,
    ControlLevel,
    IdentityState,
    RoleCode,
    SecurityContext,
    SessionState,
)
from app.security.policy import GLOBAL_ROLES, PERMISSIONS, PRIVILEGED_ROLES, PermissionSpec


POLICY_VERSION = "authorization-v1"
C2_MAX_AUTH_AGE = timedelta(minutes=15)
C3_MAX_AUTH_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    code: str
    policy: str = POLICY_VERSION
    effective_role: RoleCode | None = None


def authorize(context: SecurityContext, request: AuthorizationRequest) -> AuthorizationDecision:
    if request.now.tzinfo is None or context.authenticated_at.tzinfo is None:
        return _deny("invalid_authentication_time")
    now = request.now.astimezone(timezone.utc)
    if context.identity_state is not IdentityState.ACTIVE:
        return _deny("identity_not_active")
    if context.session_state is not SessionState.ACTIVE:
        return _deny("session_not_active")

    spec = PERMISSIONS.get(request.action)
    if spec is None:
        return _deny("unknown_action")
    if spec.tenant_required and request.tenant_id is None:
        return _deny("tenant_selection_required")
    if spec.forbid_resource_owner and request.resource_owner_id == context.actor_id:
        return _deny("self_approval_forbidden")

    candidate_failure = "no_applicable_assignment"
    for grant in context.active_grants(now):
        if not _tenant_applies(
            grant.role, grant.tenant_id, request.tenant_id, tenant_required=spec.tenant_required
        ):
            continue
        if not grant.all_modules and spec.module not in grant.modules:
            candidate_failure = "module_not_assigned"
            continue
        if spec.branch_scoped:
            if request.branch_id is None and not grant.all_branches:
                candidate_failure = "branch_selection_required"
                continue
            if request.branch_id is not None and not grant.all_branches and request.branch_id not in grant.branch_ids:
                candidate_failure = "branch_not_assigned"
                continue
        if not _role_allows(grant.role, request.action, spec, grant.conditional_permissions):
            candidate_failure = "action_not_granted"
            continue
        auth_failure = _authentication_failure(context, grant.role, spec.control_level, now)
        if auth_failure is not None:
            candidate_failure = auth_failure
            continue
        return AuthorizationDecision(True, "allowed", effective_role=grant.role)

    return _deny(candidate_failure)


def _tenant_applies(
    role: RoleCode, assigned_tenant, requested_tenant, *, tenant_required: bool
) -> bool:
    if not tenant_required and requested_tenant is None:
        return True
    if assigned_tenant is None:
        return role in GLOBAL_ROLES
    return assigned_tenant == requested_tenant


def _role_allows(
    role: RoleCode,
    action: str,
    spec: PermissionSpec,
    conditional_permissions: frozenset[str],
) -> bool:
    if role in spec.roles:
        return True
    return role in spec.conditional_roles and action in conditional_permissions


def _authentication_failure(
    context: SecurityContext, role: RoleCode, level: ControlLevel, now
) -> str | None:
    authenticated_at = context.authenticated_at.astimezone(timezone.utc)
    age = now - authenticated_at
    if age.total_seconds() < 0:
        return "invalid_authentication_time"
    if level is ControlLevel.C2 and age > C2_MAX_AUTH_AGE:
        return "recent_authentication_required"
    if level is ControlLevel.C3:
        if age > C3_MAX_AUTH_AGE:
            return "reauthentication_required"
        permitted = {AuthLevel.PASSKEY, AuthLevel.HARDWARE_KEY}
        if context.auth_level not in permitted:
            return "phishing_resistant_authentication_required"
        if role in PRIVILEGED_ROLES and context.auth_level is not AuthLevel.HARDWARE_KEY:
            return "hardware_key_required"
    return None


def _deny(code: str) -> AuthorizationDecision:
    return AuthorizationDecision(False, code)
