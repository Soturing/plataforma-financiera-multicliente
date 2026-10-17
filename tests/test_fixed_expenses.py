import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


client = TestClient(app)
ACTOR = "pytest-gastos-fijos"
PROVIDER = "Proveedor Fijo Pytest"


def cleanup():
    with psycopg.connect(get_settings().database_url) as conn:
        conn.execute(
            "DELETE FROM catalog.gastos_fijos WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = %s)",
            (PROVIDER,),
        )
        conn.execute(
            "DELETE FROM catalog.reglas_periodificacion WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = %s)",
            (PROVIDER,),
        )
        conn.execute(
            "DELETE FROM catalog.reglas_clasificacion WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = %s)",
            (PROVIDER,),
        )
        conn.execute(
            "DELETE FROM audit.aprendizajes WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = %s)",
            (PROVIDER,),
        )
        conn.execute("DELETE FROM catalog.proveedores WHERE nombre_normalizado = %s", (PROVIDER,))


def create_provider(category=None):
    body = {
        "razon_social": PROVIDER,
        "nombre_normalizado": PROVIDER,
        "actualizado_por": ACTOR,
    }
    if category:
        body["categoria"] = category
    return client.post("/api/v1/proveedores", json=body)


def test_provider_cannot_be_suggested_as_fixed_before_joining_the_list():
    cleanup()
    try:
        assert create_provider().status_code == 200
        blocked = create_provider("FIJOS")
        assert blocked.status_code == 422, blocked.text
        assert "lista de gastos fijos" in blocked.json()["detail"]
    finally:
        cleanup()


def test_fixed_list_registers_rule_and_can_be_deactivated():
    cleanup()
    try:
        provider = create_provider().json()
        rent = next(
            item for item in client.get("/api/v1/catalogos").json()["subcategorias"]
            if item["clave"] == "RENTA"
        )
        listed = client.post(
            "/api/v1/gastos-fijos",
            json={
                "proveedor_id": provider["id"], "subcategoria_id": rent["id"],
                "periodicidad": "mensual", "actualizado_por": ACTOR,
            },
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()["subcategoria"] == "Renta"
        assert any(item["proveedor_id"] == provider["id"] for item in client.get("/api/v1/gastos-fijos").json())

        # Ya en la lista, el proveedor puede sugerirse como fijo.
        assert create_provider("FIJOS").status_code == 200

        off = client.post(
            "/api/v1/gastos-fijos",
            json={"proveedor_id": provider["id"], "activa": False, "actualizado_por": ACTOR},
        )
        assert off.status_code == 200 and off.json()["activa"] is False
        assert create_provider("FIJOS").status_code == 422
    finally:
        cleanup()


def test_fixed_list_rejects_subcategory_from_another_category():
    cleanup()
    try:
        provider = create_provider().json()
        insumos = next(
            item for item in client.get("/api/v1/catalogos").json()["subcategorias"]
            if item["clave"] == "INSUMOS"
        )
        response = client.post(
            "/api/v1/gastos-fijos",
            json={"proveedor_id": provider["id"], "subcategoria_id": insumos["id"], "actualizado_por": ACTOR},
        )
        assert response.status_code == 422, response.text
    finally:
        cleanup()
