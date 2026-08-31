from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


class ActorType(str, Enum):
    PERSON = "PERSONA"
    INTEGRATION = "INTEGRACION"
    SYSTEM = "SISTEMA"


class IdentityState(str, Enum):
    INVITED = "INVITADA"
    REGISTRATION_PENDING = "REGISTRO_PENDIENTE"
    ACTIVE = "ACTIVA"
    SECURITY_LOCKED = "BLOQUEADA_SEGURIDAD"
    SUSPENDED = "SUSPENDIDA"
    TERMINATED = "BAJA_DEFINITIVA"


class SessionState(str, Enum):
    ACTIVE = "ACTIVA"
    REVOKED = "REVOCADA"
    EXPIRED = "EXPIRADA"


class AssignmentState(str, Enum):
    PENDING = "PENDIENTE"
    ACTIVE = "ACTIVA"
    SUSPENDED = "SUSPENDIDA"
    EXPIRED = "EXPIRADA"
    REVOKED = "REVOCADA"


class AuthLevel(str, Enum):
    FEDERATED = "FEDERADA"
    PASSKEY = "PASSKEY"
    HARDWARE_KEY = "LLAVE_FISICA"
    RECOVERY = "RECUPERACION"


class ControlLevel(int, Enum):
    C0 = 0
    C1 = 1
    C2 = 2
    C3 = 3


class RoleCode(str, Enum):
    CONSULTING_DIRECTOR = "CONSULTORA_DIRECTOR"
    SECURITY_ADMIN = "CONSULTORA_SEGURIDAD"
    CONSULTING_OPERATOR = "CONSULTORA_CAPTURISTA"
    CLIENT_OWNER = "CLIENTE_RESPONSABLE"
    CLIENT_FINANCE = "CLIENTE_FINANZAS"
    CLIENT_OPERATOR = "CLIENTE_OPERADOR"
    TECHNICAL_SUPPORT = "SOPORTE_TECNICO"
    API_INTEGRATION = "INTEGRACION_API"


class ModuleCode(str, Enum):
    DOCUMENTS = "DOCUMENTOS"
    INTERNAL_RECEIPTS = "COMPROBANTES_INTERNOS"
    PROVIDERS = "PROVEEDORES"
    ACCOUNTING_CATALOGS = "CATALOGOS_CONTABLES"
    SALES = "VENTAS"
    FINANCE = "FINANZAS"
    REPORTS = "REPORTES"
    PAYROLL = "NOMINA"
    INVENTORY = "INVENTARIOS"
    RECIPES = "RECETAS"
    CLIENT_ADMIN = "ADMIN_CLIENTES"
    IDENTITY_ACCESS = "IDENTIDADES_ACCESOS"
    SECURITY_AUDIT = "AUDITORIA_SEGURIDAD"
    INTEGRATIONS = "INTEGRACIONES"
    TECHNICAL_OPERATIONS = "OPERACION_TECNICA"


@dataclass(frozen=True)
class AccessGrant:
    role: RoleCode
    tenant_id: UUID | None
    modules: frozenset[ModuleCode] = field(default_factory=frozenset)
    branch_ids: frozenset[UUID] = field(default_factory=frozenset)
    conditional_permissions: frozenset[str] = field(default_factory=frozenset)
    all_modules: bool = False
    all_branches: bool = False
    state: AssignmentState = AssignmentState.ACTIVE
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    def is_current(self, now: datetime) -> bool:
        if self.state is not AssignmentState.ACTIVE:
            return False
        if self.valid_from is not None and now < _as_utc(self.valid_from):
            return False
        if self.valid_until is not None and now >= _as_utc(self.valid_until):
            return False
        return True


@dataclass(frozen=True)
class SecurityContext:
    actor_id: UUID
    provider_subject: str
    actor_type: ActorType
    session_id: UUID
    identity_state: IdentityState
    session_state: SessionState
    auth_level: AuthLevel
    authenticated_at: datetime
    grants: tuple[AccessGrant, ...]

    def active_grants(self, now: datetime) -> tuple[AccessGrant, ...]:
        return tuple(grant for grant in self.grants if grant.is_current(now))


@dataclass(frozen=True)
class AuthorizationRequest:
    action: str
    tenant_id: UUID | None = None
    branch_id: UUID | None = None
    resource_owner_id: UUID | None = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Los timestamps de seguridad deben incluir zona horaria")
    return value.astimezone(timezone.utc)
