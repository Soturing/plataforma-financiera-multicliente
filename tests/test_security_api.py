from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.api import get_control_repository, get_security_context
from app.security.control_repository import BranchScopeOption, ScopeOptions, TenantScopeOption
from app.security.models import (
    ActorType,
    AuthLevel,
    IdentityState,
    ModuleCode,
    RoleCode,
    SecurityContext,
    SessionState,
)


def test_security_context_requires_bearer_token():
    response = TestClient(app).get("/api/v1/security/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticación requerida"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_security_context_fails_closed_when_oidc_is_not_configured():
    response = TestClient(app).get(
        "/api/v1/security/me", headers={"Authorization": "Bearer synthetic.invalid.token"}
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "La autenticación segura no está configurada"}


def test_scope_options_require_bearer_token():
    response = TestClient(app).get("/api/v1/security/scope-options")

    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticación requerida"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_scope_options_return_only_server_resolved_labels():
    actor_id, session_id, tenant_id, branch_id = uuid4(), uuid4(), uuid4(), uuid4()
    context = SecurityContext(
        actor_id=actor_id,
        provider_subject="synthetic-subject",
        actor_type=ActorType.PERSON,
        session_id=session_id,
        identity_state=IdentityState.ACTIVE,
        session_state=SessionState.ACTIVE,
        auth_level=AuthLevel.HARDWARE_KEY,
        authenticated_at=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        grants=(),
    )
    resolved = ScopeOptions(
        actor_display_name="Directora sintética",
        actor_email="directora@example.test",
        tenants=(
            TenantScopeOption(
                id=tenant_id,
                slug="tenant-sintetico",
                display_name="Tenant sintético",
                state="ACTIVO",
                roles=(RoleCode.CONSULTING_DIRECTOR,),
                modules=(ModuleCode.DOCUMENTS, ModuleCode.FINANCE),
                all_modules=False,
                all_branches=False,
                branches=(
                    BranchScopeOption(
                        id=branch_id,
                        code="CENTRO",
                        display_name="Sucursal Centro",
                    ),
                ),
            ),
        ),
    )

    class FakeRepository:
        def load_scope_options(self, received):
            assert received is context
            return resolved

    app.dependency_overrides[get_security_context] = lambda: context
    app.dependency_overrides[get_control_repository] = FakeRepository
    try:
        response = TestClient(app).get("/api/v1/security/scope-options")
    finally:
        app.dependency_overrides.pop(get_security_context, None)
        app.dependency_overrides.pop(get_control_repository, None)

    assert response.status_code == 200
    body = response.json()
    assert body["actor"] == {
        "id": str(actor_id),
        "display_name": "Directora sintética",
        "email": "directora@example.test",
    }
    assert body["session"]["auth_level"] == "LLAVE_FISICA"
    assert body["tenants"] == [
        {
            "id": str(tenant_id),
            "slug": "tenant-sintetico",
            "display_name": "Tenant sintético",
            "state": "ACTIVO",
            "roles": ["CONSULTORA_DIRECTOR"],
            "modules": ["DOCUMENTOS", "FINANZAS"],
            "all_modules": False,
            "all_branches": False,
            "branches": [
                {
                    "id": str(branch_id),
                    "code": "CENTRO",
                    "display_name": "Sucursal Centro",
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/v1/security/invitations",
            {
                "email": "synthetic@example.test",
                "role": "CONSULTORA_CAPTURISTA",
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "all_modules": True,
                "all_branches": True,
                "reason": "Prueba sintética",
            },
        ),
        (
            "/api/v1/security/identities/00000000-0000-0000-0000-000000000001/suspend",
            {"reason": "Prueba sintética"},
        ),
        (
            "/api/v1/security/sessions/00000000-0000-0000-0000-000000000001/revoke",
            {"reason": "Prueba sintética"},
        ),
    ],
)
def test_lifecycle_endpoints_require_authentication(path, payload):
    response = TestClient(app).post(path, json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticación requerida"}
