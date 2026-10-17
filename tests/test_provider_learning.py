from io import BytesIO

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.main import app
from app.provider_catalog import find_provider, normalize_alias, normalize_provider_rfc


TEST_ACTOR = "pytest-learning"
TEST_CANONICAL = "Proveedor Canonico Pytest"
TEST_ALIAS = "Pr??veedor Can?nico Pytest"


def test_provider_catalog_template_is_downloadable():
    with TestClient(app) as client:
        response = client.get("/api/v1/proveedores/plantilla")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.content.startswith(b"PK")


def test_provider_catalog_template_round_trips_through_importer():
    from openpyxl import load_workbook

    from app.provider_catalog import parse_provider_file
    from app.provider_template import PROVIDER_HEADERS, build_provider_template

    workbook = load_workbook(BytesIO(build_provider_template()))
    assert [cell.value for cell in workbook["Proveedores"][1]] == PROVIDER_HEADERS
    workbook["Proveedores"].append(
        [None, "Proveedor Ficticio SA", "Proveedor Ficticio", None, "FIJOS", "RENTA", "GENERAL", "PF | P FICTICIO", "SI"]
    )
    buffer = BytesIO()
    workbook.save(buffer)

    rows = parse_provider_file("catalogo.xlsx", buffer.getvalue())

    assert len(rows) == 1
    assert rows[0]["nombre_normalizado"] == "Proveedor Ficticio"
    assert rows[0]["categoria"] == "FIJOS"


def cleanup_learning_data():
    with psycopg.connect(get_settings().database_url) as conn:
        conn.execute(
            """
            DELETE FROM core.facturas_finales
            WHERE factura_id IN (SELECT id FROM core.facturas WHERE creada_por = %s)
            """,
            (TEST_ACTOR,),
        )
        conn.execute(
            "DELETE FROM core.facturas WHERE creada_por = %s",
            (TEST_ACTOR,),
        )
        conn.execute(
            """
            DELETE FROM catalog.reglas_clasificacion
            WHERE proveedor_id IN (
                SELECT id FROM catalog.proveedores
                WHERE nombre_normalizado IN (%s, %s)
            )
            """,
            (TEST_CANONICAL, TEST_ALIAS),
        )
        conn.execute(
            "DELETE FROM catalog.proveedores WHERE nombre_normalizado IN (%s, %s)",
            (TEST_CANONICAL, TEST_ALIAS),
        )


def create_provider(client: TestClient, aliases=None):
    response = client.post(
        "/api/v1/proveedores",
        json={
            "razon_social": TEST_CANONICAL,
            "nombre_normalizado": TEST_CANONICAL,
            "nombre_comercial": "Canonico",
            "categoria": "VARIABLES",
            "centro_costo": "COCINA",
            "aliases": [TEST_ALIAS] if aliases is None else aliases,
            "actualizado_por": TEST_ACTOR,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_alias_normalization_is_accent_and_symbol_tolerant():
    assert normalize_alias(" Proveedor  Ficticio Gamma ") == "PROVEEDOR FICTICIO GAMMA"
    assert normalize_alias("Proveedor??Ficticio-Gamma") == "PROVEEDOR FICTICIO GAMMA"


def test_generic_rfc_is_not_usable_for_provider_matching():
    assert normalize_provider_rfc("XAXX010101000") is None
    assert normalize_provider_rfc(" xexx010101000 ") is None
    assert normalize_provider_rfc("PDD010101DD4") == "PDD010101DD4"


def test_catalog_alias_resolves_to_canonical_provider():
    cleanup_learning_data()
    client = TestClient(app)
    try:
        provider = create_provider(client)
        with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
            match = find_provider(conn, proposed_name=TEST_ALIAS)
            assert str(match["id"]) == provider["id"]
            assert match["nombre_normalizado"] == TEST_CANONICAL

        quality = client.get("/api/v1/calidad-datos")
        assert quality.status_code == 200, quality.text
        assert "problemas" in quality.json()
    finally:
        cleanup_learning_data()


def test_provider_csv_import_has_preview_before_commit():
    cleanup_learning_data()
    client = TestClient(app)
    csv_data = (
        "rfc,razon_social,nombre_normalizado,nombre_comercial,categoria,subcategoria,centro_costo,aliases,activo\n"
        f",{TEST_CANONICAL},{TEST_CANONICAL},Canonico,VARIABLES,,COCINA,{TEST_ALIAS},SI\n"
    ).encode("utf-8")
    try:
        preview = client.post(
            "/api/v1/proveedores/importar",
            data={"confirmar": "false", "importado_por": TEST_ACTOR},
            files={"archivo": ("catalogo.csv", BytesIO(csv_data), "text/csv")},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["creados"] == 1
        with psycopg.connect(get_settings().database_url) as conn:
            assert conn.execute(
                "SELECT count(*) FROM catalog.proveedores WHERE nombre_normalizado = %s",
                (TEST_CANONICAL,),
            ).fetchone()[0] == 0

        applied = client.post(
            "/api/v1/proveedores/importar",
            data={"confirmar": "true", "importado_por": TEST_ACTOR},
            files={"archivo": ("catalogo.csv", BytesIO(csv_data), "text/csv")},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["creados"] == 1
    finally:
        cleanup_learning_data()


def test_human_correction_can_remember_alias_and_retire_transient_provider():
    cleanup_learning_data()
    client = TestClient(app)
    try:
        canonical = create_provider(client, aliases=[])
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": TEST_ACTOR},
            files={"archivo": ("alias.jpg", BytesIO(b"demo"), "image/jpeg")},
        )
        invoice_id = created.json()["id"]
        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": TEST_ALIAS,
                "fecha_emision": "2026-08-12",
                "subtotal": "100.00",
                "iva": "16.00",
                "total": "116.00",
            },
        )
        assert processed.status_code == 200, processed.text
        corrected = client.post(
            f"/api/v1/facturas/{invoice_id}/corregir",
            json={
                "revisada_por": TEST_ACTOR,
                "recordar_alias": True,
                "correcciones": [{
                    "campo": "proveedor_nombre",
                    "valor": TEST_CANONICAL,
                    "motivo": "Normalización pytest",
                }],
            },
        )
        assert corrected.status_code == 200, corrected.text
        with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
            match = find_provider(conn, proposed_name=TEST_ALIAS)
            assert str(match["id"]) == canonical["id"]
            transient = conn.execute(
                "SELECT activo FROM catalog.proveedores WHERE nombre_normalizado = %s",
                (TEST_ALIAS,),
            ).fetchone()
            assert transient["activo"] is False
    finally:
        cleanup_learning_data()


def test_por_asignar_blocks_approval():
    cleanup_learning_data()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "POR-ASIGNAR", "creada_por": TEST_ACTOR},
            files={"archivo": ("sin-sucursal.jpg", BytesIO(b"demo"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]
        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": TEST_ALIAS,
                "fecha_emision": "2026-08-12",
                "subtotal": "100.00",
                "iva": "16.00",
                "total": "116.00",
            },
        )
        assert processed.status_code == 200, processed.text
        approved = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": TEST_ACTOR},
        )
        assert approved.status_code == 422, approved.text
        assert "sucursal real" in approved.json()["detail"]
    finally:
        cleanup_learning_data()
