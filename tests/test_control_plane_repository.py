import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest

from app.security.control_repository import ControlPlaneRepository
from app.security.models import AuthLevel, IdentityState, ModuleCode, RoleCode, SessionState
from app.security.oidc import OIDCPrincipal


CONTROL_TEST_DATABASE_URL = os.getenv("CONTROL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for control-plane integration tests",
)


def test_repository_loads_only_current_database_assignments():
    identity_id, tenant_id, branch_id, data_branch_id = uuid4(), uuid4(), uuid4(), uuid4()
    session_id, assignment_id = uuid4(), uuid4()
    provider_subject = f"pytest|{uuid4()}"
    provider_session_id = f"pytest-session-{uuid4()}"
    security_stamp = uuid4()
    now = datetime.now(timezone.utc)

    with psycopg.connect(CONTROL_TEST_DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state)
            VALUES (%s, %s, 'Tenant sintético de prueba', 'ACTIVO')
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}"),
        )
        conn.execute(
            """
            INSERT INTO control.identities (
                id, actor_type, identity_provider, provider_subject, display_name, state, security_stamp
            ) VALUES (%s, 'PERSONA', 'pytest', %s, 'Usuario sintético', 'ACTIVA', %s)
            """,
            (identity_id, provider_subject, security_stamp),
        )
        conn.execute(
            """
            INSERT INTO control.branches (id, tenant_id, data_plane_branch_id, code, display_name)
            VALUES (%s, %s, %s, 'TEST', 'Sucursal sintética')
            """,
            (branch_id, tenant_id, data_branch_id),
        )
        conn.execute(
            """
            INSERT INTO control.sessions (
                id, identity_id, provider_session_digest, security_stamp, state, auth_level,
                authenticated_at, idle_expires_at, absolute_expires_at
            ) VALUES (%s, %s, %s, %s, 'ACTIVA', 'PASSKEY', %s, %s, %s)
            """,
            (
                session_id,
                identity_id,
                sha256(provider_session_id.encode()).digest(),
                security_stamp,
                now,
                now + timedelta(minutes=30),
                now + timedelta(hours=12),
            ),
        )
        conn.execute(
            """
            INSERT INTO control.access_assignments (
                id, identity_id, tenant_id, role_code, state, created_by_identity_id
            ) VALUES (%s, %s, %s, 'CONSULTORA_CAPTURISTA', 'ACTIVA', %s)
            """,
            (assignment_id, identity_id, tenant_id, identity_id),
        )
        conn.execute(
            "INSERT INTO control.assignment_modules VALUES (%s, 'FINANZAS')",
            (assignment_id,),
        )
        conn.execute(
            "INSERT INTO control.assignment_branches VALUES (%s, %s)",
            (assignment_id, branch_id),
        )
        conn.execute(
            """
            INSERT INTO control.conditional_permissions (
                assignment_id, action_code, granted_by_identity_id, reason
            ) VALUES (%s, 'reports.csv_export', %s, 'Prueba automatizada')
            """,
            (assignment_id, identity_id),
        )
        conn.commit()

    try:
        principal = OIDCPrincipal(
            subject=provider_subject,
            provider_session_id=provider_session_id,
            authenticated_at=now,
            auth_level=AuthLevel.PASSKEY,
        )
        context = ControlPlaneRepository(CONTROL_TEST_DATABASE_URL, "pytest").load_security_context(
            principal
        )

        assert context.actor_id == identity_id
        assert context.identity_state is IdentityState.ACTIVE
        assert context.session_state is SessionState.ACTIVE
        assert len(context.grants) == 1
        loaded = context.grants[0]
        assert loaded.role is RoleCode.CONSULTING_OPERATOR
        assert loaded.tenant_id == tenant_id
        assert loaded.modules == frozenset({ModuleCode.FINANCE})
        assert loaded.branch_ids == frozenset({data_branch_id})
        assert loaded.conditional_permissions == frozenset({"reports.csv_export"})
    finally:
        with psycopg.connect(CONTROL_TEST_DATABASE_URL) as conn:
            conn.execute("DELETE FROM control.conditional_permissions WHERE assignment_id = %s", (assignment_id,))
            conn.execute("DELETE FROM control.assignment_branches WHERE assignment_id = %s", (assignment_id,))
            conn.execute("DELETE FROM control.assignment_modules WHERE assignment_id = %s", (assignment_id,))
            conn.execute("DELETE FROM control.access_assignments WHERE id = %s", (assignment_id,))
            conn.execute("DELETE FROM control.sessions WHERE id = %s", (session_id,))
            conn.execute("DELETE FROM control.branches WHERE id = %s", (branch_id,))
            conn.execute("DELETE FROM control.identities WHERE id = %s", (identity_id,))
            conn.execute("DELETE FROM control.tenants WHERE id = %s", (tenant_id,))


def test_security_audit_events_are_append_only():
    event_id = uuid4()
    with psycopg.connect(CONTROL_TEST_DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO security_audit.events (
                event_id, event_type, result, actor_type, action_code,
                request_id, sensitivity, policy_code, event_hash
            ) VALUES (%s, 'PYTEST_APPEND_ONLY', 'EXITO', 'SISTEMA', 'security.test',
                      %s, 'INTERNA', 'pytest', %s)
            """,
            (event_id, uuid4(), b"synthetic-event-hash"),
        )
        conn.execute("SAVEPOINT before_forbidden_update")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "UPDATE security_audit.events SET action_code = 'tampered' WHERE event_id = %s",
                (event_id,),
            )
        conn.execute("ROLLBACK TO SAVEPOINT before_forbidden_update")
        conn.rollback()
