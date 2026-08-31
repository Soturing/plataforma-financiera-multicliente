import pytest
from fastapi.testclient import TestClient

from app.main import app


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
