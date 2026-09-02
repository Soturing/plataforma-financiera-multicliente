import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.security.data_plane import (
    DataPlaneAccess,
    DataPlaneError,
    DataPlaneRegistration,
    FileDataPlaneRegistry,
    TenantDataPlaneRouter,
    build_data_plane_router,
    provision_data_plane_identity,
)
from app.config import Settings
from app.security.models import (
    AccessGrant,
    ActorType,
    AuthLevel,
    AuthorizationRequest,
    IdentityState,
    ModuleCode,
    RoleCode,
    SecurityContext,
    SessionState,
)


CONTROL_TEST_DATABASE_URL = os.getenv("CONTROL_TEST_DATABASE_URL")
DATA_PLANE_TEST_DATABASE_URL = os.getenv("DATA_PLANE_TEST_DATABASE_URL")
DATA_PLANE_B_TEST_DATABASE_URL = os.getenv("DATA_PLANE_B_TEST_DATABASE_URL")
NOW = datetime(2026, 8, 31, 21, 0, tzinfo=timezone.utc)


class TrackingRegistry:
    def __init__(self, registration: DataPlaneRegistration):
        self.registration = registration
        self.calls: list[str] = []

    def load(self, reference: str) -> DataPlaneRegistration:
        self.calls.append(reference)
        return self.registration


def _context(tenant_id):
    return SecurityContext(
        actor_id=uuid4(),
        provider_subject=f"pytest|{uuid4()}",
        actor_type=ActorType.PERSON,
        session_id=uuid4(),
        identity_state=IdentityState.ACTIVE,
        session_state=SessionState.ACTIVE,
        auth_level=AuthLevel.PASSKEY,
        authenticated_at=NOW - timedelta(minutes=1),
        grants=(
            AccessGrant(
                role=RoleCode.CONSULTING_OPERATOR,
                tenant_id=tenant_id,
                modules=frozenset({ModuleCode.DOCUMENTS}),
                all_branches=True,
            ),
        ),
    )


def _registration(tenant_id, reference="tenant-test"):
    return DataPlaneRegistration(
        tenant_id=tenant_id,
        reference=reference,
        database_url="postgresql://runtime:synthetic@localhost:5432/synthetic",
        upload_dir=Path("C:/synthetic/uploads"),
    )


def test_unauthorized_tenant_is_rejected_before_registry_lookup():
    allowed_tenant = uuid4()
    requested_tenant = uuid4()
    registry = TrackingRegistry(_registration(requested_tenant))
    router = TenantDataPlaneRouter("postgresql://unused", registry)

    with pytest.raises(DataPlaneError) as caught:
        router.resolve(
            _context(allowed_tenant),
            AuthorizationRequest(
                action="documents.read",
                tenant_id=requested_tenant,
                now=NOW,
            ),
            DataPlaneAccess.READ,
        )

    assert caught.value.code == "no_applicable_assignment"
    assert registry.calls == []


def test_file_registry_rejects_traversal_unknown_fields_and_unverified_tls(tmp_path):
    tenant_id = uuid4()
    registry = FileDataPlaneRegistry(tmp_path)
    with pytest.raises(DataPlaneError) as traversal:
        registry.load("../tenant-b")
    assert traversal.value.code == "invalid_data_plane_reference"

    payload = {
        "tenant_id": str(tenant_id),
        "database_url": "postgresql://runtime:synthetic@localhost:5432/synthetic?sslmode=disable",
        "upload_dir": str((tmp_path / "uploads").resolve()),
        "unexpected": True,
    }
    (tmp_path / "tenant-test.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataPlaneError) as unknown:
        registry.load("tenant-test")
    assert unknown.value.code == "invalid_data_plane_config"

    payload.pop("unexpected")
    (tmp_path / "tenant-test.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DataPlaneError) as tls:
        FileDataPlaneRegistry(tmp_path, require_tls=True).load("tenant-test")
    assert tls.value.code == "data_plane_tls_required"


def test_router_builder_requires_verified_tls_in_production(tmp_path):
    tenant_id = uuid4()
    payload = {
        "tenant_id": str(tenant_id),
        "database_url": "postgresql://runtime:synthetic@localhost:5432/synthetic?sslmode=require",
        "upload_dir": str((tmp_path / "uploads").resolve()),
    }
    (tmp_path / "tenant-test.json").write_text(json.dumps(payload), encoding="utf-8")
    settings = Settings(
        database_url="postgresql://demo:synthetic@localhost:5432/demo",
        control_database_url="postgresql://control:synthetic@localhost:5433/control",
        data_plane_config_dir=tmp_path,
        environment="production",
        enforce_business_security=True,
    )

    router = build_data_plane_router(settings)

    with pytest.raises(DataPlaneError) as caught:
        router.registry.load("tenant-test")
    assert caught.value.code == "data_plane_tls_required"


@pytest.mark.skipif(
    not DATA_PLANE_TEST_DATABASE_URL,
    reason="DATA_PLANE_TEST_DATABASE_URL is required for view-security tests",
)
def test_financial_views_use_invoker_security_before_provisioning():
    conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        views = conn.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (
                       WHERE COALESCE(c.reloptions, ARRAY[]::text[]) @> ARRAY['security_invoker=true']
                   ) AS invoker
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname IN ('analytics', 'finance')
               AND c.relkind = 'v'
            """
        ).fetchone()
        assert views["total"] > 0
        assert views["invoker"] == views["total"]
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for routing integration tests",
)
def test_read_only_tenant_rejects_writes_without_loading_secrets():
    conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        reference = f"tenant-{str(tenant_id)[:8]}"
        conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético', 'SOLO_LECTURA', %s)
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}", reference),
        )
        registry = TrackingRegistry(_registration(tenant_id, reference))
        router = TenantDataPlaneRouter(CONTROL_TEST_DATABASE_URL, registry)

        with pytest.raises(DataPlaneError) as caught:
            router.resolve(
                _context(tenant_id),
                AuthorizationRequest(action="documents.upload", tenant_id=tenant_id, now=NOW),
                DataPlaneAccess.WRITE,
                control_connection=conn,
            )

        assert caught.value.code == "tenant_read_only"
        assert registry.calls == []
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for routing integration tests",
)
def test_registry_identity_must_equal_the_authorized_tenant():
    conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        reference = f"tenant-{str(tenant_id)[:8]}"
        conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético', 'ACTIVO', %s)
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}", reference),
        )
        registry = TrackingRegistry(_registration(uuid4(), reference))
        router = TenantDataPlaneRouter(CONTROL_TEST_DATABASE_URL, registry)

        with pytest.raises(DataPlaneError) as caught:
            router.resolve(
                _context(tenant_id),
                AuthorizationRequest(action="documents.read", tenant_id=tenant_id, now=NOW),
                DataPlaneAccess.READ,
                control_connection=conn,
            )

        assert caught.value.code == "data_plane_identity_mismatch"
        assert registry.calls == [reference]
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for branch routing tests",
)
def test_router_rejects_branch_that_is_not_registered_for_the_tenant():
    conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        reference = f"tenant-{str(tenant_id)[:8]}"
        conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético', 'ACTIVO', %s)
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}", reference),
        )
        registry = TrackingRegistry(_registration(tenant_id, reference))
        router = TenantDataPlaneRouter(CONTROL_TEST_DATABASE_URL, registry)

        with pytest.raises(DataPlaneError) as caught:
            router.resolve(
                _context(tenant_id),
                AuthorizationRequest(
                    action="documents.read",
                    tenant_id=tenant_id,
                    branch_id=uuid4(),
                    now=NOW,
                ),
                DataPlaneAccess.READ,
                control_connection=conn,
            )

        assert caught.value.code == "branch_unavailable"
        assert registry.calls == []
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL,
    reason="CONTROL_TEST_DATABASE_URL is required for routing integration tests",
)
def test_control_plane_rejects_unsafe_or_reused_data_plane_references():
    conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        first_tenant = uuid4()
        reference = f"tenant-{str(first_tenant)[:8]}"
        conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético A', 'ACTIVO', %s)
            """,
            (first_tenant, f"pytest-{str(first_tenant)[:8]}", reference),
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                unsafe_tenant = uuid4()
                conn.execute(
                    """
                    INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
                    VALUES (%s, %s, 'Tenant inseguro', 'ACTIVO', '../tenant-b')
                    """,
                    (unsafe_tenant, f"pytest-{str(unsafe_tenant)[:8]}"),
                )

        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                duplicate_tenant = uuid4()
                conn.execute(
                    """
                    INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
                    VALUES (%s, %s, 'Tenant sintético B', 'ACTIVO', %s)
                    """,
                    (duplicate_tenant, f"pytest-{str(duplicate_tenant)[:8]}", reference),
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not DATA_PLANE_TEST_DATABASE_URL,
    reason="DATA_PLANE_TEST_DATABASE_URL is required for data-plane integration tests",
)
def test_data_plane_binding_is_single_assignment_and_request_context_is_immutable():
    conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        actor_id = uuid4()
        session_id = uuid4()
        branch_id = uuid4()
        assert provision_data_plane_identity(
            DATA_PLANE_TEST_DATABASE_URL,
            tenant_id,
            connection=conn,
        )
        assert not provision_data_plane_identity(
            DATA_PLANE_TEST_DATABASE_URL,
            tenant_id,
            connection=conn,
        )
        with pytest.raises(DataPlaneError) as rebound:
            provision_data_plane_identity(
                DATA_PLANE_TEST_DATABASE_URL,
                uuid4(),
                connection=conn,
            )
        assert rebound.value.code == "data_plane_already_bound"

        conn.execute("SET LOCAL ROLE tenant_runtime")
        conn.execute(
            "SELECT security_context.activate_request(%s, %s, %s, %s)",
            (tenant_id, actor_id, session_id, branch_id),
        )
        context = conn.execute(
            """
            SELECT security_context.current_tenant_id() AS tenant_id,
                   security_context.current_actor_id() AS actor_id,
                   security_context.current_session_id() AS session_id,
                   security_context.current_branch_id() AS branch_id
            """
        ).fetchone()
        assert context == {
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "session_id": session_id,
            "branch_id": branch_id,
        }

        with pytest.raises(psycopg.Error):
            conn.execute(
                "SELECT security_context.activate_request(%s, %s, %s, NULL)",
                (tenant_id, actor_id, session_id),
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not DATA_PLANE_TEST_DATABASE_URL,
    reason="DATA_PLANE_TEST_DATABASE_URL is required for data-plane integration tests",
)
def test_data_plane_rejects_an_authorized_context_for_another_tenant():
    conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        provision_data_plane_identity(DATA_PLANE_TEST_DATABASE_URL, tenant_id, connection=conn)
        conn.execute("SET LOCAL ROLE tenant_runtime")
        with pytest.raises(psycopg.Error):
            conn.execute(
                "SELECT security_context.activate_request(%s, %s, %s, NULL)",
                (uuid4(), uuid4(), uuid4()),
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not DATA_PLANE_TEST_DATABASE_URL,
    reason="DATA_PLANE_TEST_DATABASE_URL is required for principal-safety tests",
)
def test_privileged_database_owner_cannot_activate_application_context():
    conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        provision_data_plane_identity(DATA_PLANE_TEST_DATABASE_URL, tenant_id, connection=conn)

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT security_context.activate_request(%s, %s, %s, NULL)",
                (tenant_id, uuid4(), uuid4()),
            )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL or not DATA_PLANE_TEST_DATABASE_URL,
    reason="Both isolated databases are required for end-to-end routing tests",
)
def test_router_establishes_context_only_after_control_and_data_plane_agree():
    control_conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    data_conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        reference = f"tenant-{str(tenant_id)[:8]}"
        control_conn.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético', 'ACTIVO', %s)
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}", reference),
        )
        provision_data_plane_identity(
            DATA_PLANE_TEST_DATABASE_URL,
            tenant_id,
            connection=data_conn,
        )
        data_conn.execute("SET LOCAL ROLE tenant_runtime")
        registry = TrackingRegistry(_registration(tenant_id, reference))
        router = TenantDataPlaneRouter(CONTROL_TEST_DATABASE_URL, registry)
        actor = _context(tenant_id)
        request = AuthorizationRequest(
            action="documents.upload",
            tenant_id=tenant_id,
            now=NOW,
        )

        with router.connect(
            actor,
            request,
            DataPlaneAccess.WRITE,
            control_connection=control_conn,
            data_connection=data_conn,
        ) as session:
            context = session.connection.execute(
                """
                SELECT security_context.current_tenant_id() AS tenant_id,
                       security_context.current_actor_id() AS actor_id,
                       security_context.current_session_id() AS session_id
                """
            ).fetchone()
            assert context == {
                "tenant_id": tenant_id,
                "actor_id": actor.actor_id,
                "session_id": actor.session_id,
            }
            assert session.authorized.decision.allowed
    finally:
        control_conn.rollback()
        data_conn.rollback()
        control_conn.close()
        data_conn.close()


@pytest.mark.skipif(
    not DATA_PLANE_TEST_DATABASE_URL,
    reason="DATA_PLANE_TEST_DATABASE_URL is required for RLS integration tests",
)
def test_runtime_role_sees_rows_only_after_context_and_cannot_spoof_tenant():
    conn = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_id = uuid4()
        actor_id = uuid4()
        session_id = uuid4()
        provision_data_plane_identity(DATA_PLANE_TEST_DATABASE_URL, tenant_id, connection=conn)

        tables = conn.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE c.relrowsecurity AND c.relforcerowsecurity) AS protected,
                   count(*) FILTER (WHERE a.attnotnull) AS tenant_not_null
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a
                ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
             WHERE n.nspname IN ('catalog', 'core', 'ocr', 'ai', 'audit', 'finance')
               AND c.relkind IN ('r', 'p')
            """
        ).fetchone()
        assert tables["total"] > 20
        assert tables["protected"] == tables["total"]
        assert tables["tenant_not_null"] == tables["total"]

        conn.execute("SET LOCAL ROLE tenant_runtime")
        assert conn.execute("SELECT count(*) AS count FROM catalog.sucursales").fetchone()["count"] == 0

        conn.execute(
            "SELECT security_context.activate_request(%s, %s, %s, NULL)",
            (tenant_id, actor_id, session_id),
        )
        assert conn.execute("SELECT count(*) AS count FROM catalog.sucursales").fetchone()["count"] > 0

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO catalog.categorias (clave, nombre, tenant_id)
                    VALUES (%s, %s, %s)
                    """,
                    (f"PYTEST-{str(uuid4())[:8]}", "Categoría ajena sintética", uuid4()),
                )

        inserted = conn.execute(
            """
            INSERT INTO catalog.categorias (clave, nombre)
            VALUES (%s, %s)
            RETURNING tenant_id
            """,
            (f"PYTEST-{str(uuid4())[:8]}", f"Categoría sintética {uuid4()}"),
        ).fetchone()
        assert inserted["tenant_id"] == tenant_id

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("DELETE FROM audit.correcciones WHERE false")
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL
    or not DATA_PLANE_TEST_DATABASE_URL
    or not DATA_PLANE_B_TEST_DATABASE_URL,
    reason="Control and two isolated data planes are required for crossed-credential tests",
)
def test_crossed_credentials_between_two_data_planes_are_rejected_end_to_end():
    control_conn = psycopg.connect(CONTROL_TEST_DATABASE_URL, row_factory=dict_row)
    plane_a = psycopg.connect(DATA_PLANE_TEST_DATABASE_URL, row_factory=dict_row)
    plane_b = psycopg.connect(DATA_PLANE_B_TEST_DATABASE_URL, row_factory=dict_row)
    try:
        tenant_a, tenant_b = uuid4(), uuid4()
        reference_a = f"tenant-{str(tenant_a)[:8]}"
        reference_b = f"tenant-{str(tenant_b)[:8]}"
        with control_conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
                VALUES (%s, %s, %s, 'ACTIVO', %s)
                """,
                [
                    (tenant_a, f"pytest-{str(tenant_a)[:8]}", "Tenant sintético A", reference_a),
                    (tenant_b, f"pytest-{str(tenant_b)[:8]}", "Tenant sintético B", reference_b),
                ],
            )
        provision_data_plane_identity(
            DATA_PLANE_TEST_DATABASE_URL,
            tenant_a,
            connection=plane_a,
        )
        provision_data_plane_identity(
            DATA_PLANE_B_TEST_DATABASE_URL,
            tenant_b,
            connection=plane_b,
        )
        plane_a.execute("SET LOCAL ROLE tenant_runtime")
        plane_b.execute("SET LOCAL ROLE tenant_runtime")

        actor = _context(tenant_a)
        request = AuthorizationRequest(
            action="documents.upload",
            tenant_id=tenant_a,
            now=NOW,
        )
        registry = TrackingRegistry(
            DataPlaneRegistration(
                tenant_id=tenant_a,
                reference=reference_a,
                database_url=DATA_PLANE_B_TEST_DATABASE_URL,
                upload_dir=Path("C:/synthetic/tenant-a"),
            )
        )
        router = TenantDataPlaneRouter(CONTROL_TEST_DATABASE_URL, registry)

        with pytest.raises(DataPlaneError) as crossed:
            with router.connect(
                actor,
                request,
                DataPlaneAccess.WRITE,
                control_connection=control_conn,
                data_connection=plane_b,
            ):
                pass
        assert crossed.value.code == "data_plane_identity_rejected"

        with router.connect(
            actor,
            request,
            DataPlaneAccess.WRITE,
            control_connection=control_conn,
            data_connection=plane_a,
        ) as session:
            assert session.connection.execute(
                "SELECT security_context.current_tenant_id() AS tenant_id"
            ).fetchone()["tenant_id"] == tenant_a
    finally:
        control_conn.rollback()
        plane_a.rollback()
        plane_b.rollback()
        control_conn.close()
        plane_a.close()
        plane_b.close()
