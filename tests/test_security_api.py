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
