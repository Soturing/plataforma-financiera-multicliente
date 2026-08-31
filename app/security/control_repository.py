from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.security.models import (
    AccessGrant,
    ActorType,
    AssignmentState,
    AuthLevel,
    IdentityState,
    ModuleCode,
    RoleCode,
    SecurityContext,
    SessionState,
)
from app.security.oidc import OIDCPrincipal


class SecurityContextNotFound(ValueError):
    pass


class ControlPlaneRepository:
    def __init__(self, database_url: str, identity_provider: str) -> None:
        self.database_url = database_url
        self.identity_provider = identity_provider

    def load_security_context(self, principal: OIDCPrincipal) -> SecurityContext:
        session_digest = sha256(principal.provider_session_id.encode("utf-8")).digest()
        now = datetime.now(timezone.utc)
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            session = conn.execute(
                """
                SELECT
                    i.id AS actor_id,
                    i.actor_type::text AS actor_type,
                    i.state::text AS identity_state,
                    i.security_stamp AS identity_security_stamp,
                    s.id AS session_id,
                    s.state::text AS session_state,
                    s.security_stamp AS session_security_stamp,
                    s.auth_level::text AS auth_level,
                    s.authenticated_at,
                    s.idle_expires_at,
                    s.absolute_expires_at
                FROM control.identities i
                JOIN control.sessions s ON s.identity_id = i.id
                WHERE i.identity_provider = %s
                  AND i.provider_subject = %s
                  AND s.provider_session_digest = %s
                """,
                (self.identity_provider, principal.subject, session_digest),
            ).fetchone()
            if session is None:
                raise SecurityContextNotFound("Identity or application session not found")

            session_state = SessionState(session["session_state"])
            if session["identity_security_stamp"] != session["session_security_stamp"]:
                session_state = SessionState.REVOKED
            elif now >= session["absolute_expires_at"] or now >= session["idle_expires_at"]:
                session_state = SessionState.EXPIRED

            rows = conn.execute(
                """
                SELECT
                    a.id,
                    a.role_code,
                    a.tenant_id,
                    a.state::text AS state,
                    a.all_modules,
                    a.all_branches,
                    a.valid_from,
                    a.valid_until,
                    COALESCE(
                        array_agg(DISTINCT am.module_code) FILTER (WHERE am.module_code IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS modules,
                    COALESCE(
                        array_agg(DISTINCT b.data_plane_branch_id)
                            FILTER (WHERE b.data_plane_branch_id IS NOT NULL),
                        ARRAY[]::uuid[]
                    ) AS branch_ids,
                    COALESCE(
                        array_agg(DISTINCT cp.action_code)
                            FILTER (
                                WHERE cp.action_code IS NOT NULL
                                  AND (cp.valid_until IS NULL OR cp.valid_until > %s)
                            ),
                        ARRAY[]::text[]
                    ) AS conditional_permissions
                FROM control.access_assignments a
                LEFT JOIN control.assignment_modules am ON am.assignment_id = a.id
                LEFT JOIN control.assignment_branches ab ON ab.assignment_id = a.id
                LEFT JOIN control.branches b ON b.id = ab.branch_id AND b.active
                LEFT JOIN control.conditional_permissions cp ON cp.assignment_id = a.id
                WHERE a.identity_id = %s
                GROUP BY a.id
                """,
                (now, session["actor_id"]),
            ).fetchall()

        grants = tuple(
            AccessGrant(
                role=RoleCode(row["role_code"]),
                tenant_id=row["tenant_id"],
                modules=frozenset(ModuleCode(value) for value in row["modules"]),
                branch_ids=frozenset(UUID(str(value)) for value in row["branch_ids"]),
                conditional_permissions=frozenset(row["conditional_permissions"]),
                all_modules=row["all_modules"],
                all_branches=row["all_branches"],
                state=AssignmentState(row["state"]),
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
            )
            for row in rows
        )
        # The database session is authoritative. A token claim can never raise its assurance level.
        database_auth_level = AuthLevel(session["auth_level"])
        auth_level = _minimum_auth_level(database_auth_level, principal.auth_level)
        return SecurityContext(
            actor_id=session["actor_id"],
            provider_subject=principal.subject,
            actor_type=ActorType(session["actor_type"]),
            session_id=session["session_id"],
            identity_state=IdentityState(session["identity_state"]),
            session_state=session_state,
            auth_level=auth_level,
            authenticated_at=min(session["authenticated_at"], principal.authenticated_at),
            grants=grants,
        )


_AUTH_STRENGTH = {
    AuthLevel.RECOVERY: 0,
    AuthLevel.FEDERATED: 1,
    AuthLevel.PASSKEY: 2,
    AuthLevel.HARDWARE_KEY: 3,
}


def _minimum_auth_level(left: AuthLevel, right: AuthLevel) -> AuthLevel:
    return min((left, right), key=_AUTH_STRENGTH.__getitem__)
