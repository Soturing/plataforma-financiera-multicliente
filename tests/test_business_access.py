import json
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import app
from app.security.business_access import (
    BusinessDataAccess,
    SECURED_BUSINESS_ROUTES,
    get_optional_business_security_context,
    is_secured_business_request,
)
from app.security.data_plane import provision_data_plane_identity
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
from app.security.route_policy import BUSINESS_ROUTE_POLICIES


CONTROL_TEST_DATABASE_URL = os.getenv("CONTROL_TEST_DATABASE_URL")
BUSINESS_DATA_PLANE_TEST_DATABASE_URL = os.getenv("BUSINESS_DATA_PLANE_TEST_DATABASE_URL")
BUSINESS_RUNTIME_DATABASE_URL = os.getenv("BUSINESS_RUNTIME_DATABASE_URL")


def _security_context(tenant_id, branch_id):
    return SecurityContext(
        actor_id=uuid4(),
        provider_subject="pytest|secure-operator",
        actor_type=ActorType.PERSON,
        session_id=uuid4(),
        identity_state=IdentityState.ACTIVE,
        session_state=SessionState.ACTIVE,
        auth_level=AuthLevel.PASSKEY,
        authenticated_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        grants=(
            AccessGrant(
                role=RoleCode.CONSULTING_OPERATOR,
                tenant_id=tenant_id,
                modules=frozenset({ModuleCode.DOCUMENTS}),
                branch_ids=frozenset({branch_id}),
            ),
        ),
    )


def test_production_cannot_start_with_business_security_disabled():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://runtime:synthetic@localhost/synthetic",
            environment="production",
            enforce_business_security=False,
        )


def test_secure_route_allowlist_is_explicit_and_matches_real_catalog_entries():
    assert SECURED_BUSINESS_ROUTES < set(BUSINESS_ROUTE_POLICIES)
    assert is_secured_business_request("GET", "/api/v1/facturas/00000000-0000-0000-0000-000000000001")
    assert is_secured_business_request("GET", "/api/v1/duplicados")
    assert is_secured_business_request(
        "GET", "/api/v1/duplicados/00000000-0000-0000-0000-000000000001/archivo"
    )
    assert not is_secured_business_request("GET", "/api/v1/proveedores")
    assert not is_secured_business_request("DELETE", "/api/v1/facturas/00000000-0000-0000-0000-000000000001")


def test_every_allowlisted_route_is_wired_to_its_declared_data_plane_policy():
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            key = (method, route.path)
            marked = [
                dependency.call
                for dependency in route.dependant.dependencies
                if hasattr(dependency.call, "business_security_action")
            ]
            if key in SECURED_BUSINESS_ROUTES:
                assert len(marked) == 1, key
                dependency = marked[0]
                policy = BUSINESS_ROUTE_POLICIES[key]
                assert dependency.business_security_action == policy.actions[0]
                assert dependency.business_data_plane_access is policy.access
                seen.add(key)
            else:
                assert not marked, key
    assert seen == set(SECURED_BUSINESS_ROUTES)


def test_secure_actor_reference_ignores_browser_supplied_identity():
    tenant_id, branch_id = uuid4(), uuid4()
    context = _security_context(tenant_id, branch_id)
    access = BusinessDataAccess(
        connection=object(),
        action="documents.approve",
        tenant_id=tenant_id,
        branch_id=branch_id,
        upload_dir=Path("C:/synthetic/uploads"),
        security=context,
    )

    assert access.actor_reference("persona-suplantada") == str(context.actor_id)


def test_resource_branch_is_authorized_against_session_assignments():
    tenant_id, assigned_branch, other_branch = uuid4(), uuid4(), uuid4()
    access = BusinessDataAccess(
        connection=object(),
        action="documents.read",
        tenant_id=tenant_id,
        branch_id=assigned_branch,
        upload_dir=Path("C:/synthetic/uploads"),
        security=_security_context(tenant_id, assigned_branch),
    )

    access.require_branch(assigned_branch)
    with pytest.raises(HTTPException) as caught:
        access.require_branch(other_branch)
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "branch_not_assigned"


def test_cross_branch_duplicate_is_denied_before_it_can_be_resolved():
    tenant_id, assigned_branch, other_branch = uuid4(), uuid4(), uuid4()

    class DuplicateConnection:
        def execute(self, *_args, **_kwargs):
            return self

        def fetchall(self):
            return [
                {
                    "sucursal_id": assigned_branch,
                    "original_branch_id": other_branch,
                    "duplicate_branch_id": None,
                }
            ]

    access = BusinessDataAccess(
        connection=DuplicateConnection(),
        action="documents.duplicates.discard",
        tenant_id=tenant_id,
        branch_id=assigned_branch,
        upload_dir=Path("C:/synthetic/uploads"),
        security=_security_context(tenant_id, assigned_branch),
    )

    with pytest.raises(HTTPException) as caught:
        access.require_duplicate_branches([uuid4()])
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "branch_not_assigned"


def test_secure_mode_blocks_unintegrated_routes_and_requires_authentication_on_integrated_routes():
    settings = Settings(
        database_url="postgresql://runtime:synthetic@localhost/synthetic",
        control_database_url="postgresql://control:synthetic@localhost/control",
        oidc_identity_provider="synthetic-idp",
        oidc_issuer="https://id.example.test/",
        oidc_audience="https://api.example.test",
        oidc_jwks_url="https://id.example.test/jwks.json",
        data_plane_config_dir=Path("C:/synthetic/registry"),
        environment="test",
        enforce_business_security=True,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        blocked = client.get("/api/v1/proveedores")
        protected = client.get("/api/v1/revision")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert blocked.status_code == 503
    assert blocked.json() == {"detail": {"code": "route_not_security_integrated"}}
    assert protected.status_code == 401
    assert protected.json() == {"detail": "Autenticación requerida"}


@pytest.mark.skipif(
    not CONTROL_TEST_DATABASE_URL
    or not BUSINESS_DATA_PLANE_TEST_DATABASE_URL
    or not BUSINESS_RUNTIME_DATABASE_URL,
    reason="Isolated control, owner and runtime databases are required",
)
def test_invoice_upload_uses_session_actor_tenant_branch_and_append_only_audit(tmp_path):
    tenant_id = uuid4()
    actor_id = uuid4()
    session_id = uuid4()
    control_branch_id = uuid4()
    other_control_branch_id = uuid4()
    request_id = uuid4()
    rejected_request_id = uuid4()
    reference = f"tenant-{str(tenant_id)[:8]}"
    now = datetime.now(timezone.utc)

    with psycopg.connect(BUSINESS_DATA_PLANE_TEST_DATABASE_URL) as data_connection:
        branch_id = data_connection.execute(
            "SELECT id FROM catalog.sucursales WHERE clave = 'DEMO-A'"
        ).fetchone()[0]
        other_branch_id = data_connection.execute(
            "SELECT id FROM catalog.sucursales WHERE clave = 'DEMO-B'"
        ).fetchone()[0]
        provision_data_plane_identity(
            BUSINESS_DATA_PLANE_TEST_DATABASE_URL,
            tenant_id,
            connection=data_connection,
        )

    with psycopg.connect(CONTROL_TEST_DATABASE_URL) as control_connection:
        security_stamp = uuid4()
        control_connection.execute(
            """
            INSERT INTO control.tenants (id, slug, display_name, state, data_plane_reference)
            VALUES (%s, %s, 'Tenant sintético', 'ACTIVO', %s)
            """,
            (tenant_id, f"pytest-{str(tenant_id)[:8]}", reference),
        )
        with control_connection.cursor() as cursor:
            cursor.executemany(
            """
            INSERT INTO control.branches (
                id, tenant_id, data_plane_branch_id, code, display_name, active
            ) VALUES (%s, %s, %s, %s, %s, true)
            """,
                [
                    (
                        control_branch_id,
                        tenant_id,
                        branch_id,
                        "DEMO-A",
                        "Sucursal sintética A",
                    ),
                    (
                        other_control_branch_id,
                        tenant_id,
                        other_branch_id,
                        "DEMO-B",
                        "Sucursal sintética B",
                    ),
                ],
            )
        control_connection.execute(
            """
            INSERT INTO control.identities (
                id, actor_type, identity_provider, provider_subject,
                display_name, state, security_stamp
            ) VALUES (%s, 'PERSONA', 'pytest', %s, 'Operador sintético', 'ACTIVA', %s)
            """,
            (actor_id, f"pytest|{actor_id}", security_stamp),
        )
        control_connection.execute(
            """
            INSERT INTO control.sessions (
                id, identity_id, provider_session_digest, security_stamp, state,
                auth_level, authenticated_at, idle_expires_at, absolute_expires_at
            ) VALUES (%s, %s, %s, %s, 'ACTIVA', 'PASSKEY', %s, %s, %s)
            """,
            (
                session_id,
                actor_id,
                sha256(str(session_id).encode()).digest(),
                security_stamp,
                now,
                now + timedelta(hours=1),
                now + timedelta(hours=8),
            ),
        )

    with psycopg.connect(BUSINESS_DATA_PLANE_TEST_DATABASE_URL) as data_connection:
        other_invoice_id = data_connection.execute(
            """
            INSERT INTO core.facturas (
                sucursal_id, archivo_url, archivo_nombre, archivo_mime,
                archivo_sha256, creada_por, tenant_id
            ) VALUES (%s, %s, 'otra-sucursal.jpg', 'image/jpeg', %s, 'fixture', %s)
            RETURNING id
            """,
            (
                other_branch_id,
                str((tmp_path / "other-branch.jpg").resolve()),
                f"pytest-{uuid4()}",
                tenant_id,
            ),
        ).fetchone()[0]
    registry_dir = tmp_path / "registry"
    upload_dir = tmp_path / "uploads"
    registry_dir.mkdir()
    (registry_dir / f"{reference}.json").write_text(
        json.dumps(
            {
                "tenant_id": str(tenant_id),
                "database_url": BUSINESS_RUNTIME_DATABASE_URL,
                "upload_dir": str(upload_dir.resolve()),
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        database_url=BUSINESS_DATA_PLANE_TEST_DATABASE_URL,
        control_database_url=CONTROL_TEST_DATABASE_URL,
        data_plane_config_dir=registry_dir,
        environment="testing",
        enforce_business_security=True,
    )
    context = _security_context(tenant_id, branch_id)
    context = SecurityContext(**{**context.__dict__, "actor_id": actor_id, "session_id": session_id})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_optional_business_security_context] = lambda: context
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/facturas",
            headers={
                "X-Tenant-Id": str(tenant_id),
                "X-Branch-Id": str(branch_id),
                "X-Request-Id": str(request_id),
            },
            data={
                "sucursal_clave": "DEMO-A",
                "creada_por": "identidad-enviada-por-el-navegador",
            },
            files={"archivo": ("factura.jpg", BytesIO(b"synthetic-image"), "image/jpeg")},
        )
        assert response.status_code == 201, response.text
        invoice_id = response.json()["id"]
        duplicate_path = upload_dir / "duplicado-detectado.jpg"
        duplicate_path.parent.mkdir(parents=True, exist_ok=True)
        duplicate_path.write_bytes(b"synthetic-duplicate")
        with psycopg.connect(BUSINESS_DATA_PLANE_TEST_DATABASE_URL) as data_connection:
            duplicate_id = data_connection.execute(
                """
                INSERT INTO core.documentos_duplicados (
                    factura_original_id, archivo_url, archivo_nombre,
                    archivo_sha256, criterio, valor_coincidente,
                    sucursal_id, tenant_id
                ) VALUES (%s, %s, 'duplicado-detectado.jpg', %s,
                          'sha256', %s, %s, %s)
                RETURNING id
                """,
                (
                    invoice_id,
                    str(duplicate_path.resolve()),
                    sha256(b"synthetic-duplicate").hexdigest(),
                    sha256(b"synthetic-duplicate").hexdigest(),
                    branch_id,
                    tenant_id,
                ),
            ).fetchone()[0]
        business_headers = {
            "X-Tenant-Id": str(tenant_id),
            "X-Branch-Id": str(branch_id),
        }
        duplicates = client.get("/api/v1/duplicados", headers=business_headers)
        duplicate_file_response = client.get(
            f"/api/v1/duplicados/{duplicate_id}/archivo",
            headers=business_headers,
        )
        discarded = client.post(
            "/api/v1/duplicados/descartar",
            headers=business_headers,
            json={
                "duplicado_ids": [str(duplicate_id)],
                "descartado_por": "identidad-enviada-por-el-navegador",
            },
        )
        denied = client.get(
            f"/api/v1/facturas/{other_invoice_id}",
            headers={
                "X-Tenant-Id": str(tenant_id),
                "X-Branch-Id": str(branch_id),
                "X-Request-Id": str(rejected_request_id),
            },
        )
    finally:
        app.dependency_overrides.pop(get_optional_business_security_context, None)
        app.dependency_overrides.pop(get_settings, None)

    assert duplicates.status_code == 200, duplicates.text
    assert {item["id"] for item in duplicates.json()} == {str(duplicate_id)}
    assert duplicate_file_response.status_code == 200
    assert duplicate_file_response.content == b"synthetic-duplicate"
    assert discarded.status_code == 200, discarded.text
    assert discarded.json() == {"descartados": 1, "archivos_eliminados": 1}
    assert not duplicate_path.exists()
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "branch_not_assigned"
    with psycopg.connect(BUSINESS_DATA_PLANE_TEST_DATABASE_URL) as data_connection:
        invoice = data_connection.execute(
            "SELECT creada_por, tenant_id, sucursal_id FROM core.facturas WHERE id = %s",
            (invoice_id,),
        ).fetchone()
        duplicate_actor = data_connection.execute(
            "SELECT resuelto_por FROM core.documentos_duplicados WHERE id = %s",
            (duplicate_id,),
        ).fetchone()[0]
    assert invoice == (str(actor_id), tenant_id, branch_id)
    assert duplicate_actor == str(actor_id)

    with psycopg.connect(CONTROL_TEST_DATABASE_URL) as control_connection:
        event = control_connection.execute(
            """
            SELECT result::text, actor_id, tenant_id, branch_id, action_code, request_id
              FROM security_audit.events
             WHERE request_id = %s
            """,
            (request_id,),
        ).fetchone()
    assert event == (
        "EXITO",
        actor_id,
        tenant_id,
        control_branch_id,
        "documents.upload",
        request_id,
    )

    with psycopg.connect(CONTROL_TEST_DATABASE_URL) as control_connection:
        rejection = control_connection.execute(
            """
            SELECT result::text, actor_id, tenant_id, branch_id,
                   action_code, reason_code, request_id
              FROM security_audit.events
             WHERE request_id = %s AND result = 'RECHAZO'
            """,
            (rejected_request_id,),
        ).fetchone()
    assert rejection == (
        "RECHAZO",
        actor_id,
        tenant_id,
        other_control_branch_id,
        "documents.read",
        "branch_not_assigned",
        rejected_request_id,
    )
