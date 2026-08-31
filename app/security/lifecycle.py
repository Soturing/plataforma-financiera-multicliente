from __future__ import annotations

import hmac
import re
import secrets
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.security.authorization import AuthorizationDecision, authorize
from app.security.models import (
    AuthorizationRequest,
    ModuleCode,
    RoleCode,
    SecurityContext,
)
from app.security.policy import PERMISSIONS


INVITATION_LIFETIME = timedelta(hours=24)
BOOTSTRAP_LIFETIME = timedelta(minutes=30)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
STRICT_GLOBAL_ASSIGNMENT_ROLES = frozenset(
    {RoleCode.CONSULTING_DIRECTOR, RoleCode.SECURITY_ADMIN}
)
PRIVILEGED_ROLES = frozenset({RoleCode.CONSULTING_DIRECTOR, RoleCode.SECURITY_ADMIN})


class LifecycleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InvitationCommand:
    email: str
    role: RoleCode
    tenant_id: UUID | None
    modules: frozenset[ModuleCode] = field(default_factory=frozenset)
    branch_ids: frozenset[UUID] = field(default_factory=frozenset)
    conditional_permissions: frozenset[str] = field(default_factory=frozenset)
    all_modules: bool = False
    all_branches: bool = False
    assignment_valid_until: datetime | None = None
    reason: str = ""


@dataclass(frozen=True)
class InvitationCreated:
    invitation_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class BootstrapDirectorCommand:
    provider_subject: str
    email: str
    display_name: str
    primary_authenticator_id: str
    backup_authenticator_id: str


class IdentityLifecycleService:
    def __init__(self, database_url: str, identity_provider: str) -> None:
        self.database_url = database_url
        self.identity_provider = identity_provider

    def create_invitation(
        self,
        actor: SecurityContext,
        command: InvitationCommand,
        *,
        request_id: UUID | None = None,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> InvitationCreated:
        now = _utc(now)
        request_id = request_id or uuid4()
        normalized_email = _normalize_email(command.email)
        reason = _required_reason(command.reason)
        _validate_invitation_scope(command, now)

        invite_decision = _require(actor, "identities.invite", None, now)
        if _requires_global_assignment(command):
            assignment_decision = _require(actor, "identities.assign_global", None, now)
        else:
            assignment_decision = _require(actor, "identities.assign", command.tenant_id, now)

        with self._connection(connection) as conn:
            actor_row = conn.execute(
                "SELECT lower(email) AS email FROM control.identities WHERE id = %s",
                (actor.actor_id,),
            ).fetchone()
            if actor_row is None:
                raise LifecycleError("actor_not_found", "La identidad administradora no existe")
            if actor_row["email"] == normalized_email:
                raise LifecycleError("self_assignment_forbidden", "No puede invitarse ni ampliarse a sí mismo")

            # Serialize invitations for the same recipient and tenant so two
            # concurrent requests cannot leave two usable tokens behind.
            invitation_lock = f"{normalized_email}|{command.tenant_id or 'global'}"
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (invitation_lock,),
            )

            if command.tenant_id is not None:
                tenant = conn.execute(
                    "SELECT state::text AS state FROM control.tenants WHERE id = %s FOR SHARE",
                    (command.tenant_id,),
                ).fetchone()
                if tenant is None or tenant["state"] != "ACTIVO":
                    raise LifecycleError("tenant_not_active", "El tenant no está activo")
                _verify_branches(conn, command.tenant_id, command.branch_ids)

            invitation_id = uuid4()
            raw_token = secrets.token_urlsafe(48)
            expires_at = now + INVITATION_LIFETIME
            conn.execute(
                """
                INSERT INTO control.invitations (
                    id, email, tenant_id, token_digest, proposed_role_code,
                    proposed_valid_until, proposed_all_modules, proposed_all_branches,
                    reason, expires_at, invited_by_identity_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invitation_id,
                    normalized_email,
                    command.tenant_id,
                    sha256(raw_token.encode("utf-8")).digest(),
                    command.role.value,
                    command.assignment_valid_until,
                    command.all_modules,
                    command.all_branches,
                    reason,
                    expires_at,
                    actor.actor_id,
                ),
            )
            _insert_invitation_scope(conn, invitation_id, command)
            conn.execute(
                """
                UPDATE control.invitations
                   SET replaced_by_id = %s
                 WHERE id <> %s
                   AND email = %s
                   AND tenant_id IS NOT DISTINCT FROM %s
                   AND consumed_at IS NULL
                   AND revoked_at IS NULL
                   AND replaced_by_id IS NULL
                """,
                (invitation_id, invitation_id, normalized_email, command.tenant_id),
            )
            _append_event(
                conn,
                actor=actor,
                decision=assignment_decision,
                event_type="IDENTITY_INVITATION_CREATED",
                action_code="identities.invite",
                tenant_id=command.tenant_id,
                resource_type="invitation",
                resource_id=str(invitation_id),
                reason_code=reason,
                request_id=request_id,
                sensitivity="CONFIDENCIAL",
                metadata={
                    "target_role": command.role.value,
                    "module_count": len(command.modules),
                    "branch_count": len(command.branch_ids),
                    "conditional_permission_count": len(command.conditional_permissions),
                    "invite_policy": invite_decision.policy,
                },
            )
            return InvitationCreated(invitation_id, raw_token, expires_at)

    def suspend_identity(
        self,
        actor: SecurityContext,
        target_identity_id: UUID,
        reason: str,
        *,
        request_id: UUID | None = None,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> None:
        now = _utc(now)
        request_id = request_id or uuid4()
        reason = _required_reason(reason)
        if target_identity_id == actor.actor_id:
            raise LifecycleError("self_suspension_forbidden", "No puede suspender su propia identidad")

        with self._connection(connection) as conn:
            target = conn.execute(
                """
                SELECT i.email,
                       EXISTS (
                           SELECT 1 FROM control.access_assignments a
                            WHERE a.identity_id = i.id
                              AND a.role_code IN ('CONSULTORA_DIRECTOR', 'CONSULTORA_SEGURIDAD')
                              AND a.state = 'ACTIVA'
                       ) AS privileged
                  FROM control.identities i
                 WHERE i.id = %s
                 FOR UPDATE
                """,
                (target_identity_id,),
            ).fetchone()
            if target is None:
                raise LifecycleError("identity_not_found", "La identidad no existe")
            action = "identities.suspend_privileged" if target["privileged"] else "identities.suspend"
            decision = _require(actor, action, None, now)

            conn.execute(
                """
                UPDATE control.identities
                   SET state = 'SUSPENDIDA', security_stamp = gen_random_uuid(), updated_at = %s
                 WHERE id = %s
                """,
                (now, target_identity_id),
            )
            sessions = conn.execute(
                """
                UPDATE control.sessions
                   SET state = 'REVOCADA', revoked_at = %s, revocation_reason = %s
                 WHERE identity_id = %s AND state = 'ACTIVA'
                """,
                (now, reason, target_identity_id),
            ).rowcount
            assignments = conn.execute(
                """
                UPDATE control.access_assignments
                   SET state = 'SUSPENDIDA', updated_at = %s
                 WHERE identity_id = %s AND state IN ('PENDIENTE', 'ACTIVA')
                """,
                (now, target_identity_id),
            ).rowcount
            if target["email"]:
                conn.execute(
                    """
                    UPDATE control.invitations
                       SET revoked_at = %s, revocation_reason = %s
                     WHERE email = lower(%s)
                       AND consumed_at IS NULL AND revoked_at IS NULL AND replaced_by_id IS NULL
                    """,
                    (now, reason, target["email"]),
                )
            _append_event(
                conn,
                actor=actor,
                decision=decision,
                event_type="IDENTITY_SUSPENDED",
                action_code=action,
                tenant_id=None,
                resource_type="identity",
                resource_id=str(target_identity_id),
                reason_code=reason,
                request_id=request_id,
                sensitivity="CRITICA" if target["privileged"] else "CONFIDENCIAL",
                metadata={"sessions_revoked": sessions, "assignments_suspended": assignments},
            )

    def revoke_session(
        self,
        actor: SecurityContext,
        target_session_id: UUID,
        reason: str,
        *,
        request_id: UUID | None = None,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> None:
        now = _utc(now)
        request_id = request_id or uuid4()
        reason = _required_reason(reason)
        with self._connection(connection) as conn:
            target = conn.execute(
                "SELECT identity_id, state::text AS state FROM control.sessions WHERE id = %s FOR UPDATE",
                (target_session_id,),
            ).fetchone()
            if target is None:
                raise LifecycleError("session_not_found", "La sesión no existe")
            action = "sessions.revoke_self" if target["identity_id"] == actor.actor_id else "sessions.revoke_any"
            decision = _require(actor, action, None, now)
            changed = 0
            if target["state"] == "ACTIVA":
                changed = conn.execute(
                    """
                    UPDATE control.sessions
                       SET state = 'REVOCADA', revoked_at = %s, revocation_reason = %s
                     WHERE id = %s AND state = 'ACTIVA'
                    """,
                    (now, reason, target_session_id),
                ).rowcount
            _append_event(
                conn,
                actor=actor,
                decision=decision,
                event_type="SESSION_REVOKED",
                action_code=action,
                tenant_id=None,
                resource_type="session",
                resource_id=str(target_session_id),
                reason_code=reason,
                request_id=request_id,
                sensitivity="CONFIDENCIAL",
                metadata={"state_changed": bool(changed)},
            )

    def prepare_first_director_bootstrap(
        self,
        *,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> tuple[str, datetime]:
        now = _utc(now)
        raw_token = secrets.token_urlsafe(48)
        expires_at = now + BOOTSTRAP_LIFETIME
        with self._connection(connection) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('control.first_director'))")
            existing = conn.execute(
                """
                SELECT bootstrap_token_digest, bootstrap_token_expires_at, completed_at
                  FROM control.installation_state WHERE singleton
                """
            ).fetchone()
            if existing and existing["completed_at"] is not None:
                raise LifecycleError("bootstrap_completed", "El primer director ya fue creado")
            if (
                existing
                and existing["bootstrap_token_digest"] is not None
                and existing["bootstrap_token_expires_at"] > now
            ):
                raise LifecycleError("bootstrap_pending", "Ya existe una credencial de instalación pendiente")
            conn.execute(
                """
                INSERT INTO control.installation_state (
                    singleton, bootstrap_token_digest, bootstrap_token_created_at, bootstrap_token_expires_at
                ) VALUES (true, %s, %s, %s)
                ON CONFLICT (singleton) DO UPDATE SET
                    bootstrap_token_digest = EXCLUDED.bootstrap_token_digest,
                    bootstrap_token_created_at = EXCLUDED.bootstrap_token_created_at,
                    bootstrap_token_expires_at = EXCLUDED.bootstrap_token_expires_at
                """,
                (sha256(raw_token.encode("utf-8")).digest(), now, expires_at),
            )
        return raw_token, expires_at

    def create_first_director(
        self,
        bootstrap_token: str,
        command: BootstrapDirectorCommand,
        *,
        request_id: UUID | None = None,
        now: datetime | None = None,
        connection: Connection | None = None,
    ) -> UUID:
        now = _utc(now)
        request_id = request_id or uuid4()
        email = _normalize_email(command.email)
        _bounded_required(command.provider_subject, "provider_subject", 500)
        _bounded_required(command.display_name, "display_name", 200)
        _bounded_required(command.primary_authenticator_id, "primary_authenticator_id", 500)
        _bounded_required(command.backup_authenticator_id, "backup_authenticator_id", 500)
        if command.primary_authenticator_id == command.backup_authenticator_id:
            raise LifecycleError("distinct_authenticators_required", "Se requieren dos llaves físicas distintas")
        if not bootstrap_token:
            raise LifecycleError("bootstrap_token_required", "Falta la credencial de instalación")

        with self._connection(connection) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('control.first_director'))")
            state = conn.execute(
                """
                SELECT bootstrap_token_digest, bootstrap_token_expires_at, completed_at
                  FROM control.installation_state
                 WHERE singleton
                 FOR UPDATE
                """
            ).fetchone()
            supplied_digest = sha256(bootstrap_token.encode("utf-8")).digest()
            if (
                state is None
                or state["completed_at"] is not None
                or state["bootstrap_token_digest"] is None
                or state["bootstrap_token_expires_at"] <= now
                or not hmac.compare_digest(bytes(state["bootstrap_token_digest"]), supplied_digest)
            ):
                raise LifecycleError("invalid_bootstrap_token", "La credencial de instalación no es válida")

            identity_id = uuid4()
            conn.execute(
                """
                INSERT INTO control.identities (
                    id, actor_type, identity_provider, provider_subject,
                    email, display_name, state
                ) VALUES (%s, 'PERSONA', %s, %s, %s, %s, 'ACTIVA')
                """,
                (
                    identity_id,
                    self.identity_provider,
                    command.provider_subject,
                    email,
                    command.display_name.strip(),
                ),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO control.authenticators (
                        identity_id, provider_authenticator_id, kind, label, state
                    ) VALUES (%s, %s, 'HARDWARE_KEY', %s, 'ACTIVO')
                    """,
                    [
                        (identity_id, command.primary_authenticator_id, "Llave física principal"),
                        (identity_id, command.backup_authenticator_id, "Llave física de respaldo"),
                    ],
                )
            conn.execute(
                """
                INSERT INTO control.access_assignments (
                    identity_id, tenant_id, role_code, state, all_modules,
                    all_branches, reason, created_by_identity_id
                ) VALUES (%s, NULL, 'CONSULTORA_DIRECTOR', 'ACTIVA', true, true,
                          'Instalación inicial controlada', %s)
                """,
                (identity_id, identity_id),
            )
            conn.execute(
                """
                UPDATE control.installation_state
                   SET bootstrap_token_digest = NULL,
                       bootstrap_token_created_at = NULL,
                       bootstrap_token_expires_at = NULL,
                       completed_at = %s,
                       completed_by_identity_id = %s
                 WHERE singleton
                """,
                (now, identity_id),
            )
            conn.execute(
                """
                SELECT security_audit.append_event(
                    'FIRST_DIRECTOR_CREATED', 'EXITO', %s, 'PERSONA',
                    'CONSULTORA_DIRECTOR', NULL, 'IDENTIDADES_ACCESOS', NULL,
                    'identities.bootstrap_director', 'identity', %s, NULL,
                    'LLAVE_FISICA', 'controlled_installation', %s, NULL, 1, NULL,
                    'CRITICA', 'bootstrap-v1', %s
                )
                """,
                (
                    identity_id,
                    str(identity_id),
                    request_id,
                    Jsonb({"hardware_authenticator_count": 2}),
                ),
            )
            return identity_id

    def _connection(self, existing: Connection | None):
        if existing is not None:
            return nullcontext(existing)
        return psycopg.connect(self.database_url, row_factory=dict_row)


def _require(
    actor: SecurityContext, action: str, tenant_id: UUID | None, now: datetime
) -> AuthorizationDecision:
    decision = authorize(actor, AuthorizationRequest(action=action, tenant_id=tenant_id, now=now))
    if not decision.allowed:
        raise LifecycleError(decision.code, "La política de autorización rechazó la operación")
    return decision


def _validate_invitation_scope(command: InvitationCommand, now: datetime) -> None:
    if command.role is RoleCode.API_INTEGRATION:
        raise LifecycleError("human_invitation_required", "Las integraciones no usan invitaciones humanas")
    if command.role in STRICT_GLOBAL_ASSIGNMENT_ROLES:
        if command.tenant_id is not None:
            raise LifecycleError("global_role_cannot_have_tenant", "Un rol global no lleva tenant")
    elif command.role is not RoleCode.TECHNICAL_SUPPORT and command.tenant_id is None:
        raise LifecycleError("tenant_required", "La asignación requiere tenant")
    if not command.all_modules and not command.modules:
        raise LifecycleError("module_scope_required", "Debe elegir módulos o todos los módulos")
    if command.tenant_id is not None and not command.all_branches and not command.branch_ids:
        raise LifecycleError("branch_scope_required", "Debe elegir sucursales o todas las sucursales")
    if command.assignment_valid_until is not None:
        if command.assignment_valid_until.tzinfo is None:
            raise LifecycleError("timezone_required", "La vigencia debe incluir zona horaria")
        if command.assignment_valid_until.astimezone(timezone.utc) <= now:
            raise LifecycleError("invalid_assignment_expiration", "La vigencia debe ser futura")
    for action in command.conditional_permissions:
        spec = PERMISSIONS.get(action)
        if (
            action != action.strip()
            or len(action) > 150
            or spec is None
            or command.role not in spec.conditional_roles
            or (not command.all_modules and spec.module not in command.modules)
        ):
            raise LifecycleError("invalid_conditional_permission", "Hay permisos condicionados inválidos")


def _requires_global_assignment(command: InvitationCommand) -> bool:
    return command.role in STRICT_GLOBAL_ASSIGNMENT_ROLES or (
        command.role is RoleCode.TECHNICAL_SUPPORT and command.tenant_id is None
    )


def _verify_branches(conn: Connection, tenant_id: UUID, branch_ids: frozenset[UUID]) -> None:
    if not branch_ids:
        return
    rows = conn.execute(
        "SELECT id FROM control.branches WHERE tenant_id = %s AND active AND id = ANY(%s)",
        (tenant_id, list(branch_ids)),
    ).fetchall()
    if {row["id"] for row in rows} != set(branch_ids):
        raise LifecycleError("branch_outside_tenant", "Una sucursal no pertenece al tenant seleccionado")


def _insert_invitation_scope(
    conn: Connection, invitation_id: UUID, command: InvitationCommand
) -> None:
    if command.modules:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO control.invitation_modules VALUES (%s, %s)",
                [
                    (invitation_id, module.value)
                    for module in sorted(command.modules, key=lambda item: item.value)
                ],
            )
    if command.branch_ids:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO control.invitation_branches VALUES (%s, %s)",
                [(invitation_id, branch_id) for branch_id in sorted(command.branch_ids, key=str)],
            )
    if command.conditional_permissions:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO control.invitation_conditional_permissions VALUES (%s, %s)",
                [(invitation_id, action) for action in sorted(command.conditional_permissions)],
            )


def _append_event(
    conn: Connection,
    *,
    actor: SecurityContext,
    decision: AuthorizationDecision,
    event_type: str,
    action_code: str,
    tenant_id: UUID | None,
    resource_type: str,
    resource_id: str,
    reason_code: str,
    request_id: UUID,
    sensitivity: str,
    metadata: dict[str, Any],
) -> None:
    conn.execute(
        """
        SELECT security_audit.append_event(
            %s, 'EXITO', %s, %s, %s, %s, 'IDENTIDADES_ACCESOS', NULL,
            %s, %s, %s, %s, %s, %s, %s, NULL, 1, NULL, %s, %s, %s
        )
        """,
        (
            event_type,
            actor.actor_id,
            actor.actor_type.value,
            decision.effective_role.value if decision.effective_role else None,
            tenant_id,
            action_code,
            resource_type,
            resource_id,
            actor.session_id,
            actor.auth_level.value,
            reason_code,
            request_id,
            sensitivity,
            decision.policy,
            Jsonb(metadata),
        ),
    )


def _normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise LifecycleError("invalid_email", "El correo no es válido")
    return email


def _required_reason(value: str) -> str:
    reason = value.strip()
    if not 3 <= len(reason) <= 500:
        raise LifecycleError("reason_required", "Se requiere un motivo de 3 a 500 caracteres")
    return reason


def _bounded_required(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise LifecycleError("invalid_field", f"{field_name} no es válido")
    return normalized


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise LifecycleError("timezone_required", "La fecha debe incluir zona horaria")
    return value.astimezone(timezone.utc)
