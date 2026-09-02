from __future__ import annotations

from dataclasses import dataclass

from app.security.models import ControlLevel, ModuleCode, RoleCode


@dataclass(frozen=True)
class PermissionSpec:
    module: ModuleCode
    roles: frozenset[RoleCode]
    conditional_roles: frozenset[RoleCode] = frozenset()
    control_level: ControlLevel = ControlLevel.C0
    tenant_required: bool = True
    branch_scoped: bool = False
    forbid_resource_owner: bool = False


D = RoleCode.CONSULTING_DIRECTOR
S = RoleCode.SECURITY_ADMIN
C = RoleCode.CONSULTING_OPERATOR
R = RoleCode.CLIENT_OWNER
F = RoleCode.CLIENT_FINANCE
O = RoleCode.CLIENT_OPERATOR
T = RoleCode.TECHNICAL_SUPPORT
I = RoleCode.API_INTEGRATION


def _roles(*roles: RoleCode) -> frozenset[RoleCode]:
    return frozenset(roles)


# Every accepted action must appear here. Unknown actions are denied, including for directors.
PERMISSIONS: dict[str, PermissionSpec] = {
    # Documents and invoices.
    "documents.read": PermissionSpec(
        ModuleCode.DOCUMENTS, _roles(D, C, R, F), branch_scoped=True
    ),
    "documents.original.read": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C, R, F),
        control_level=ControlLevel.C1,
        branch_scoped=True,
    ),
    "documents.upload": PermissionSpec(ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True),
    "documents.bulk_upload": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "documents.review": PermissionSpec(ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True),
    "documents.approve": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C1,
        branch_scoped=True,
    ),
    "documents.edit_approved": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "documents.change_expense": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "documents.periodify": PermissionSpec(ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True),
    "documents.delete_pending": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "documents.cancel_batch": PermissionSpec(
        ModuleCode.DOCUMENTS,
        _roles(D, C),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "documents.reprocess": PermissionSpec(ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True),
    "documents.duplicates.read": PermissionSpec(
        ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True
    ),
    "documents.duplicates.discard": PermissionSpec(
        ModuleCode.DOCUMENTS, _roles(D, C), branch_scoped=True
    ),
    # Internal receipts.
    "receipts.read": PermissionSpec(ModuleCode.INTERNAL_RECEIPTS, _roles(D, C, R, F, O)),
    "receipts.create": PermissionSpec(
        ModuleCode.INTERNAL_RECEIPTS, _roles(D, C, R, O), conditional_roles=_roles(F)
    ),
    "receipts.update": PermissionSpec(
        ModuleCode.INTERNAL_RECEIPTS, _roles(D, C, R), conditional_roles=_roles(F, O)
    ),
    "receipts.approve": PermissionSpec(
        ModuleCode.INTERNAL_RECEIPTS,
        _roles(D, C, R),
        conditional_roles=_roles(F),
        control_level=ControlLevel.C2,
        forbid_resource_owner=True,
    ),
    "receipts.download": PermissionSpec(
        ModuleCode.INTERNAL_RECEIPTS, _roles(D, C, R, F, O), control_level=ControlLevel.C1
    ),
    "receipts.replace": PermissionSpec(
        ModuleCode.INTERNAL_RECEIPTS, _roles(D, C), conditional_roles=_roles(R, F)
    ),
    # Providers and accounting catalogs.
    "providers.read": PermissionSpec(ModuleCode.PROVIDERS, _roles(D, C, R, F, O)),
    "providers.write": PermissionSpec(ModuleCode.PROVIDERS, _roles(D, C)),
    "providers.import": PermissionSpec(
        ModuleCode.PROVIDERS, _roles(D, C), control_level=ControlLevel.C2
    ),
    "providers.learning.read": PermissionSpec(
        ModuleCode.PROVIDERS, _roles(D, C), conditional_roles=_roles(R)
    ),
    "accounting_catalogs.read": PermissionSpec(
        ModuleCode.ACCOUNTING_CATALOGS, _roles(D, C, R, F, O)
    ),
    "accounting_catalogs.write": PermissionSpec(
        ModuleCode.ACCOUNTING_CATALOGS, _roles(D), control_level=ControlLevel.C2
    ),
    # Sales, finance, payroll and reports.
    "sales.read": PermissionSpec(ModuleCode.SALES, _roles(D, C, R, F, O), branch_scoped=True),
    "sales.write": PermissionSpec(
        ModuleCode.SALES, _roles(D, C, F, O), conditional_roles=_roles(R), branch_scoped=True
    ),
    "sales.correct_closed": PermissionSpec(
        ModuleCode.SALES,
        _roles(D),
        conditional_roles=_roles(C, F),
        control_level=ControlLevel.C2,
        branch_scoped=True,
    ),
    "finance.read": PermissionSpec(ModuleCode.FINANCE, _roles(D, C, R, F, O), branch_scoped=True),
    "payroll.read": PermissionSpec(ModuleCode.PAYROLL, _roles(D, C, R, F), control_level=ControlLevel.C1),
    "reports.pdf": PermissionSpec(
        ModuleCode.REPORTS, _roles(D, C, R, F), conditional_roles=_roles(O), control_level=ControlLevel.C1
    ),
    "reports.csv_export": PermissionSpec(
        ModuleCode.REPORTS,
        _roles(D),
        conditional_roles=_roles(C, R, F),
        control_level=ControlLevel.C3,
    ),
    "reports.cross_tenant": PermissionSpec(
        ModuleCode.REPORTS, _roles(D), control_level=ControlLevel.C3, tenant_required=False
    ),
    # Client, identity and security administration.
    "tenants.create": PermissionSpec(ModuleCode.CLIENT_ADMIN, _roles(D, S), tenant_required=False),
    "tenants.configure": PermissionSpec(
        ModuleCode.CLIENT_ADMIN, _roles(D), conditional_roles=_roles(S), control_level=ControlLevel.C2
    ),
    "tenants.suspend": PermissionSpec(
        ModuleCode.CLIENT_ADMIN, _roles(D), control_level=ControlLevel.C3
    ),
    "identities.invite": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS, _roles(D, S), tenant_required=False
    ),
    "identities.assign": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS, _roles(D, S), control_level=ControlLevel.C2
    ),
    "identities.assign_global": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS,
        _roles(D),
        conditional_roles=_roles(S),
        control_level=ControlLevel.C3,
        tenant_required=False,
    ),
    "identities.suspend": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS, _roles(D, S), control_level=ControlLevel.C2, tenant_required=False
    ),
    "identities.suspend_privileged": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS,
        _roles(D, S),
        control_level=ControlLevel.C3,
        tenant_required=False,
    ),
    "sessions.revoke_any": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS, _roles(D, S), control_level=ControlLevel.C2, tenant_required=False
    ),
    "sessions.revoke_self": PermissionSpec(
        ModuleCode.IDENTITY_ACCESS, _roles(D, S, C, R, F, O, T), tenant_required=False
    ),
    "audit.read_global": PermissionSpec(
        ModuleCode.SECURITY_AUDIT, _roles(D, S), tenant_required=False
    ),
    "audit.read_tenant": PermissionSpec(
        ModuleCode.SECURITY_AUDIT, _roles(D, S, R), conditional_roles=_roles(C)
    ),
    "audit.export": PermissionSpec(
        ModuleCode.SECURITY_AUDIT,
        _roles(D),
        conditional_roles=_roles(S),
        control_level=ControlLevel.C3,
        tenant_required=False,
    ),
    "alerts.manage": PermissionSpec(ModuleCode.SECURITY_AUDIT, _roles(D, S), tenant_required=False),
    # Integrations and technical operation.
    "integrations.credentials.manage": PermissionSpec(
        ModuleCode.INTEGRATIONS, _roles(D), conditional_roles=_roles(S), control_level=ControlLevel.C3
    ),
    "integration.invoke": PermissionSpec(ModuleCode.INTEGRATIONS, frozenset(), conditional_roles=_roles(I)),
    "operations.read": PermissionSpec(
        ModuleCode.TECHNICAL_OPERATIONS, _roles(D, S, T), tenant_required=False
    ),
}


GLOBAL_ROLES = frozenset({D, S, T})
PRIVILEGED_ROLES = frozenset({D, S})
