from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["version"].count(".") == 2


def test_ui_and_catalogs_are_available():
    with TestClient(app) as client:
        ui = client.get("/")
        catalogs = client.get("/api/v1/catalogos")
    assert ui.status_code == 200
    assert "Documentos por revisar" in ui.text
    assert "Análisis de gastos" in ui.text
    assert 'aria-label="Navegación principal"' in ui.text
    assert 'data-route="finance"' in ui.text
    assert 'id="nav-toggle"' in ui.text
    assert catalogs.status_code == 200
    branches = {item["clave"] for item in catalogs.json()["sucursales"]}
    assert branches >= {"DEMO-A", "DEMO-B", "DEMO-C", "POR-ASIGNAR"}
    assert "DEMO-01" not in branches
    demo_a = next(item for item in catalogs.json()["sucursales"] if item["clave"] == "DEMO-A")
    assert demo_a["rfc"] == "DEM010101AA1"
