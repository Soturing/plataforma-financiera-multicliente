from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.security import (
    AccessGrant,
    ActorType,
    AuthLevel,
    AuthorizationRequest,
    IdentityState,
    ModuleCode,
    RoleCode,
    SecurityContext,
    SessionState,
    authorize,
)
from app.security.models import AssignmentState


NOW = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def context(*grants: AccessGrant, auth_level=AuthLevel.PASSKEY, auth_age_minutes=1):
    return SecurityContext(
        actor_id=uuid4(),
        provider_subject="idp|synthetic-user",
        actor_type=ActorType.PERSON,
        session_id=uuid4(),
        identity_state=IdentityState.ACTIVE,
        session_state=SessionState.ACTIVE,
        auth_level=auth_level,
        authenticated_at=NOW - timedelta(minutes=auth_age_minutes),
        grants=tuple(grants),
    )


def grant(role, tenant_id, *modules, **kwargs):
    return AccessGrant(role=role, tenant_id=tenant_id, modules=frozenset(modules), **kwargs)


def request(action, tenant_id=None, **kwargs):
    return AuthorizationRequest(action=action, tenant_id=tenant_id, now=NOW, **kwargs)


def test_cross_tenant_access_is_denied_even_when_module_matches():
    tenant_a, tenant_b = uuid4(), uuid4()
    actor = context(grant(RoleCode.CONSULTING_OPERATOR, tenant_a, ModuleCode.FINANCE))

    decision = authorize(actor, request("finance.read", tenant_b))

    assert not decision.allowed
    assert decision.code == "no_applicable_assignment"


def test_operator_cannot_use_unassigned_module():
    tenant = uuid4()
    actor = context(grant(RoleCode.CONSULTING_OPERATOR, tenant, ModuleCode.DOCUMENTS))

    decision = authorize(actor, request("finance.read", tenant))

    assert not decision.allowed
    assert decision.code == "module_not_assigned"


def test_security_admin_cannot_read_financial_content():
    tenant = uuid4()
    actor = context(
        grant(RoleCode.SECURITY_ADMIN, None, all_modules=True, all_branches=True),
        auth_level=AuthLevel.HARDWARE_KEY,
    )

    decision = authorize(actor, request("finance.read", tenant))

    assert not decision.allowed
    assert decision.code == "action_not_granted"


def test_creator_cannot_approve_own_internal_receipt():
    tenant = uuid4()
    actor = context(grant(RoleCode.CONSULTING_OPERATOR, tenant, ModuleCode.INTERNAL_RECEIPTS))

    decision = authorize(
        actor,
        request("receipts.approve", tenant, resource_owner_id=actor.actor_id),
    )

    assert not decision.allowed
    assert decision.code == "self_approval_forbidden"


def test_csv_export_requires_explicit_conditional_permission():
    tenant = uuid4()
    without_export = context(grant(RoleCode.CONSULTING_OPERATOR, tenant, ModuleCode.REPORTS))
    with_export = context(
        grant(
            RoleCode.CONSULTING_OPERATOR,
            tenant,
            ModuleCode.REPORTS,
            conditional_permissions=frozenset({"reports.csv_export"}),
        )
    )

    assert not authorize(without_export, request("reports.csv_export", tenant)).allowed
    assert authorize(with_export, request("reports.csv_export", tenant)).allowed


def test_director_must_select_a_tenant_for_financial_access():
    actor = context(
        grant(RoleCode.CONSULTING_DIRECTOR, None, all_modules=True, all_branches=True),
        auth_level=AuthLevel.HARDWARE_KEY,
    )

    decision = authorize(actor, request("finance.read"))

    assert not decision.allowed
    assert decision.code == "tenant_selection_required"


def test_director_can_access_explicit_tenant_but_not_unknown_action():
    actor = context(
        grant(RoleCode.CONSULTING_DIRECTOR, None, all_modules=True, all_branches=True),
        auth_level=AuthLevel.HARDWARE_KEY,
    )
    tenant = uuid4()

    assert authorize(actor, request("finance.read", tenant)).allowed
    assert not authorize(actor, request("audit.delete", tenant)).allowed


def test_branch_scope_is_enforced_when_resource_has_a_branch():
    tenant, assigned_branch, other_branch = uuid4(), uuid4(), uuid4()
    actor = context(
        grant(
            RoleCode.CLIENT_OPERATOR,
            tenant,
            ModuleCode.SALES,
            branch_ids=frozenset({assigned_branch}),
        )
    )

    assert authorize(actor, request("sales.read", tenant, branch_id=assigned_branch)).allowed
    denied = authorize(actor, request("sales.read", tenant, branch_id=other_branch))
    assert not denied.allowed
    assert denied.code == "branch_not_assigned"


@pytest.mark.parametrize(
    ("assignment_state", "expected_code"),
    [
        (AssignmentState.SUSPENDED, "no_applicable_assignment"),
        (AssignmentState.REVOKED, "no_applicable_assignment"),
        (AssignmentState.EXPIRED, "no_applicable_assignment"),
    ],
)
def test_inactive_assignment_is_denied(assignment_state, expected_code):
    tenant = uuid4()
    actor = context(
        grant(
            RoleCode.CONSULTING_OPERATOR,
            tenant,
            ModuleCode.DOCUMENTS,
            state=assignment_state,
        )
    )

    decision = authorize(actor, request("documents.read", tenant))

    assert not decision.allowed
    assert decision.code == expected_code


def test_expired_assignment_is_denied_even_if_state_remains_active():
    tenant = uuid4()
    actor = context(
        grant(
            RoleCode.CONSULTING_OPERATOR,
            tenant,
            ModuleCode.DOCUMENTS,
            valid_until=NOW,
        )
    )

    assert not authorize(actor, request("documents.read", tenant)).allowed


def test_c2_action_requires_recent_authentication():
    tenant = uuid4()
    actor = context(
        grant(RoleCode.CONSULTING_OPERATOR, tenant, ModuleCode.DOCUMENTS),
        auth_age_minutes=16,
    )

    decision = authorize(actor, request("documents.edit_approved", tenant))

    assert not decision.allowed
    assert decision.code == "recent_authentication_required"


def test_director_c3_action_requires_recent_hardware_key():
    actor = context(
        grant(RoleCode.CONSULTING_DIRECTOR, None, all_modules=True, all_branches=True),
        auth_level=AuthLevel.PASSKEY,
    )

    decision = authorize(actor, request("reports.cross_tenant"))

    assert not decision.allowed
    assert decision.code == "hardware_key_required"


def test_revoked_session_denies_every_action():
    tenant = uuid4()
    active = context(grant(RoleCode.CONSULTING_OPERATOR, tenant, ModuleCode.DOCUMENTS))
    revoked = SecurityContext(**{**active.__dict__, "session_state": SessionState.REVOKED})

    decision = authorize(revoked, request("documents.read", tenant))

    assert not decision.allowed
    assert decision.code == "session_not_active"


def test_user_can_revoke_own_session_without_global_scope():
    tenant = uuid4()
    actor = context(
        grant(
            RoleCode.CLIENT_FINANCE,
            tenant,
            ModuleCode.IDENTITY_ACCESS,
            all_branches=True,
        )
    )

    decision = authorize(actor, request("sessions.revoke_self"))

    assert decision.allowed


def test_privileged_suspension_requires_recent_hardware_key():
    actor = context(
        grant(RoleCode.SECURITY_ADMIN, None, all_modules=True, all_branches=True),
        auth_level=AuthLevel.PASSKEY,
    )

    decision = authorize(actor, request("identities.suspend_privileged"))

    assert not decision.allowed
    assert decision.code == "hardware_key_required"
