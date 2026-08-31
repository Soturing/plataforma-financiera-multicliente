import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.security.lifecycle import (
    BootstrapDirectorCommand,
    IdentityLifecycleService,
    InvitationCommand,
    LifecycleError,
)
from app.security.models import (
    AccessGrant,
    ActorType,
    AuthLevel,
    IdentityState,
    ModuleCode,
    RoleCode,
    SecurityContext,
    SessionState,
)


CONTROL_TEST_DATABASE_URL = os.getenv("CONTROL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for identity lifecycle tests",
)
NOW = datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc)


def _open_rollback_connection():
    return psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)


def _seed_identity(conn, *, email, role, tenant_id=None, auth_level=AuthLevel.HARDWARE_KEY):
    identity_id, session_id, security_stamp = uuid4(), uuid4(), uuid4()
    provider_subject = f"pytest|{uuid4()}"
    provider_session = f"pytest-session-{uuid4()}"
    conn.execute(
        """
        INSERT INTO control.identities (
            id, actor_type, identity_provider, provider_subject, email,
            display_name, state, security_stamp
        ) VALUES (%s, 'PERSONA', 'pytest', %s, %s, 'Usuario sintético', 'ACTIVA', %s)
        """,
        (identity_id, provider_subject, email, security_stamp),
    )
    conn.execute(
        """
        INSERT INTO control.sessions (
            id, identity_id, provider_session_digest, security_stamp, state,
            auth_level, authenticated_at, idle_expires_at, absolute_expires_at
        ) VALUES (%s, %s, %s, %s, 'ACTIVA', %s, %s, %s, %s)
        """,
        (
            session_id,
            identity_id,
            sha256(provider_session.encode()).digest(),
            security_stamp,
            auth_level.value,
            NOW - timedelta(minutes=1),
            NOW + timedelta(minutes=30),
            NOW + timedelta(hours=8),
        ),
    )
    conn.execute(
        """
        INSERT INTO control.access_assignments (
            identity_id, tenant_id, role_code, state, all_modules,
            all_branches, reason, created_by_identity_id
        ) VALUES (%s, %s, %s, 'ACTIVA', true, true, 'Prueba sintética', %s)
        """,
        (identity_id, tenant_id, role.value, identity_id),
    )
    grant = AccessGrant(
        role=role,
        tenant_id=tenant_id,
        all_modules=True,
        all_branches=True,
    )
    context = SecurityContext(
        actor_id=identity_id,
        provider_subject=provider_subject,
        actor_type=ActorType.PERSON,
        session_id=session_id,
        identity_state=IdentityState.ACTIVE,
        session_state=SessionState.ACTIVE,
        auth_level=auth_level,
        authenticated_at=NOW - timedelta(minutes=1),
        grants=(grant,),
    )
    return context


def _seed_tenant_and_branch(conn):
    tenant_id, branch_id, data_branch_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "INSERT INTO control.tenants (id, slug, display_name, state) VALUES (%s, %s, %s, 'ACTIVO')",
        (tenant_id, f"pytest-{str(tenant_id)[:8]}", "Tenant sintético"),
    )
    conn.execute(
        """
        INSERT INTO control.branches (id, tenant_id, data_plane_branch_id, code, display_name)
        VALUES (%s, %s, %s, 'TEST', 'Sucursal sintética')
        """,
        (branch_id, tenant_id, data_branch_id),
    )
    return tenant_id, branch_id


def test_invitation_is_single_use_scoped_and_audited_without_plaintext_token():
    conn = _open_rollback_connection()
    try:
        tenant_id, branch_id = _seed_tenant_and_branch(conn)
        director = _seed_identity(
            conn, email=f"director-{uuid4()}@example.test", role=RoleCode.CONSULTING_DIRECTOR
        )
        service = IdentityLifecycleService(CONTROL_TEST_DATABASE_URL, "pytest")
        command = InvitationCommand(
            email=f"capturista-{uuid4()}@example.test",
            role=RoleCode.CONSULTING_OPERATOR,
            tenant_id=tenant_id,
            modules=frozenset({ModuleCode.DOCUMENTS, ModuleCode.FINANCE, ModuleCode.REPORTS}),
            branch_ids=frozenset({branch_id}),
            conditional_permissions=frozenset({"reports.csv_export"}),
            reason="Asignación operativa aprobada",
        )

        first = service.create_invitation(director, command, now=NOW, connection=conn)
        second = service.create_invitation(director, command, now=NOW, connection=conn)

        invitations = conn.execute(
            """
            SELECT id, token_digest, replaced_by_id, proposed_all_modules, proposed_all_branches
              FROM control.invitations
             WHERE id IN (%s, %s)
             ORDER BY created_at, id
            """,
            (first.invitation_id, second.invitation_id),
        ).fetchall()
        by_id = {row["id"]: row for row in invitations}
        assert first.token.encode() not in bytes(by_id[first.invitation_id]["token_digest"])
        assert by_id[first.invitation_id]["replaced_by_id"] == second.invitation_id
        assert by_id[second.invitation_id]["replaced_by_id"] is None
        assert conn.execute(
            "SELECT count(*) AS count FROM control.invitation_modules WHERE invitation_id = %s",
            (second.invitation_id,),
        ).fetchone()["count"] == 3
        assert conn.execute(
            "SELECT count(*) AS count FROM control.invitation_branches WHERE invitation_id = %s",
            (second.invitation_id,),
        ).fetchone()["count"] == 1

        events = conn.execute(
            """
            SELECT previous_hash, event_hash, metadata
              FROM security_audit.events
             WHERE resource_id IN (%s, %s)
             ORDER BY sequence_id
            """,
            (str(first.invitation_id), str(second.invitation_id)),
        ).fetchall()
        assert len(events) == 2
        assert events[1]["previous_hash"] == events[0]["event_hash"]
        assert "email" not in events[0]["metadata"]
        assert "token" not in events[0]["metadata"]
    finally:
        conn.rollback()
        conn.close()


def test_security_admin_cannot_assign_global_role_without_explicit_permission():
    conn = _open_rollback_connection()
    try:
        security_admin = _seed_identity(
            conn,
            email=f"security-{uuid4()}@example.test",
            role=RoleCode.SECURITY_ADMIN,
        )
        service = IdentityLifecycleService(CONTROL_TEST_DATABASE_URL, "pytest")
        command = InvitationCommand(
            email=f"new-director-{uuid4()}@example.test",
            role=RoleCode.CONSULTING_DIRECTOR,
            tenant_id=None,
            all_modules=True,
            all_branches=True,
            reason="Designación global solicitada",
        )

        with pytest.raises(LifecycleError) as caught:
            service.create_invitation(security_admin, command, now=NOW, connection=conn)

        assert caught.value.code == "action_not_granted"
        assert conn.execute("SELECT count(*) AS count FROM control.invitations").fetchone()["count"] == 0
    finally:
        conn.rollback()
        conn.close()


def test_suspension_revokes_sessions_and_suspends_assignments_atomically():
    conn = _open_rollback_connection()
    try:
        tenant_id, _ = _seed_tenant_and_branch(conn)
        director = _seed_identity(
            conn, email=f"director-{uuid4()}@example.test", role=RoleCode.CONSULTING_DIRECTOR
        )
        target = _seed_identity(
            conn,
            email=f"target-{uuid4()}@example.test",
            role=RoleCode.CONSULTING_OPERATOR,
            tenant_id=tenant_id,
            auth_level=AuthLevel.PASSKEY,
        )
        service = IdentityLifecycleService(CONTROL_TEST_DATABASE_URL, "pytest")

        service.suspend_identity(
            director,
            target.actor_id,
            "Baja preventiva solicitada por dirección",
            now=NOW,
            connection=conn,
        )

        identity = conn.execute(
            "SELECT state::text AS state FROM control.identities WHERE id = %s", (target.actor_id,)
        ).fetchone()
        session = conn.execute(
            "SELECT state::text AS state FROM control.sessions WHERE id = %s", (target.session_id,)
        ).fetchone()
        assignment = conn.execute(
            """
            SELECT state::text AS state FROM control.access_assignments
             WHERE identity_id = %s ORDER BY created_at DESC LIMIT 1
            """,
            (target.actor_id,),
        ).fetchone()
        assert identity["state"] == "SUSPENDIDA"
        assert session["state"] == "REVOCADA"
        assert assignment["state"] == "SUSPENDIDA"
    finally:
        conn.rollback()
        conn.close()


def test_first_director_requires_two_keys_and_consumes_bootstrap_token():
    conn = _open_rollback_connection()
    try:
        service = IdentityLifecycleService(CONTROL_TEST_DATABASE_URL, "pytest")
        token, expires_at = service.prepare_first_director_bootstrap(now=NOW, connection=conn)
        assert expires_at == NOW + timedelta(minutes=30)

        identity_id = service.create_first_director(
            token,
            BootstrapDirectorCommand(
                provider_subject=f"pytest|director-{uuid4()}",
                email=f"first-director-{uuid4()}@example.test",
                display_name="Director sintético",
                primary_authenticator_id=f"hardware-primary-{uuid4()}",
                backup_authenticator_id=f"hardware-backup-{uuid4()}",
            ),
            now=NOW,
            connection=conn,
        )

        assert conn.execute(
            "SELECT count(*) AS count FROM control.authenticators WHERE identity_id = %s",
            (identity_id,),
        ).fetchone()["count"] == 2
        assignment = conn.execute(
            """
            SELECT role_code, tenant_id, all_modules, all_branches
              FROM control.access_assignments WHERE identity_id = %s
            """,
            (identity_id,),
        ).fetchone()
        assert assignment["role_code"] == "CONSULTORA_DIRECTOR"
        assert assignment["tenant_id"] is None
        assert assignment["all_modules"] and assignment["all_branches"]

        with pytest.raises(LifecycleError) as caught:
            service.create_first_director(
                token,
                BootstrapDirectorCommand(
                    provider_subject="pytest|replay",
                    email="replay@example.test",
                    display_name="Replay",
                    primary_authenticator_id="hardware-a",
                    backup_authenticator_id="hardware-b",
                ),
                now=NOW,
                connection=conn,
            )
        assert caught.value.code == "invalid_bootstrap_token"
    finally:
        conn.rollback()
        conn.close()


def test_expired_bootstrap_token_can_be_safely_replaced():
    conn = _open_rollback_connection()
    try:
        service = IdentityLifecycleService(CONTROL_TEST_DATABASE_URL, "pytest")
        expired_token, _ = service.prepare_first_director_bootstrap(now=NOW, connection=conn)
        replacement, replacement_expiration = service.prepare_first_director_bootstrap(
            now=NOW + timedelta(minutes=31), connection=conn
        )

        assert replacement != expired_token
        assert replacement_expiration == NOW + timedelta(minutes=61)
        stored = conn.execute(
            "SELECT bootstrap_token_digest FROM control.installation_state WHERE singleton"
        ).fetchone()
        assert bytes(stored["bootstrap_token_digest"]) == sha256(replacement.encode()).digest()
    finally:
        conn.rollback()
        conn.close()
