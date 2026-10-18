import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.main import app
from app.ocr_processing import reading_context
from apoyo_db import conexion_pruebas

client = TestClient(app)
NAME = "Razon Propia Pytest SA"
RFC = "RPP010203AB1"


def cleanup():
    with conexion_pruebas() as conn:
        conn.execute("DELETE FROM catalog.entidades_propias WHERE nombre = %s", (NAME,))


def test_own_entity_is_saved_and_used_by_the_reading_context():
    cleanup()
    try:
        saved = client.post(
            "/api/v1/entidades-propias",
            json={"nombre": NAME, "rfc": "rpp-010203-ab1", "actualizado_por": "pytest"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["rfc"] == RFC
        assert any(item["nombre"] == NAME for item in client.get("/api/v1/entidades-propias").json())

        with conexion_pruebas(row_factory=dict_row) as conn:
            own_rfcs, own_names, known = reading_context(conn)
        assert RFC in own_rfcs and NAME in own_names
        assert RFC not in known
    finally:
        cleanup()


def test_own_entity_rejects_generic_or_malformed_rfc():
    for rfc in ("XAXX010101000", "123"):
        response = client.post(
            "/api/v1/entidades-propias",
            json={"nombre": NAME, "rfc": rfc, "actualizado_por": "pytest"},
        )
        assert response.status_code == 422, response.text
