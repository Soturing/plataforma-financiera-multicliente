import psycopg
import pytest
from psycopg.rows import dict_row

from app.branch_detection import apply_detected_branch, detect_branch, infer_branch_by_consumption
from app.config import get_settings
from app.ocr.base import OcrDocument
from app.ocr_processing import persist_ocr_result
from apoyo_db import conexion_pruebas


def test_detects_demo_a_by_recipient_rfc():
    with conexion_pruebas(row_factory=dict_row) as conn:
        detected = detect_branch(
            conn,
            """
            RECEPTOR
            RESTAURANTE DEMO UNO S.A. DE C.V.
            RFC RECEPTOR: DEM010101AA1
            """,
        )

    assert detected is not None
    assert detected["clave"] == "DEMO-A"
    assert detected["confianza"] == 1


def test_detects_demo_a_by_known_alias():
    with conexion_pruebas(row_factory=dict_row) as conn:
        detected = detect_branch(conn, "Cliente: RESTAURANTE DEMO UNO")

    assert detected is not None
    assert detected["clave"] == "DEMO-A"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RFC RECEPTOR DEM010101BB2 RESTAURANTE DEMO DOS", "DEMO-B"),
        ("RFC RECEPTOR DEM010101CC3 RESTAURANTE DEMO TRES", "DEMO-C"),
    ],
)
def test_detects_other_operational_restaurants(text, expected):
    with conexion_pruebas(row_factory=dict_row) as conn:
        detected = detect_branch(conn, text)

    assert detected is not None
    assert detected["clave"] == expected
    assert detected["confianza"] == 1


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ("FILETE SIRLOIN COSTILLA TORERITA", "DEMO-A"),
        ("PULPA NEGRA TOP SIRLOIN DIEZMILLO", "DEMO-C"),
        ("RIB EYE DIEZMILLO SIRLOIN", "DEMO-B"),
    ],
)
def test_infers_restaurant_from_product_combination(items, expected):
    with conexion_pruebas(row_factory=dict_row) as conn:
        inferred = infer_branch_by_consumption(conn, f"PROVEEDOR FICTICIO ALFA\nDETALLE\n{items}")

    assert inferred is not None
    assert inferred["clave"] == expected
    assert inferred["nivel"] == "alta"
    assert len(inferred["productos"]) >= 3


def test_shared_products_alone_remain_low_confidence():
    with conexion_pruebas(row_factory=dict_row) as conn:
        inferred = infer_branch_by_consumption(conn, "SIRLOIN DIEZMILLO")

    assert inferred is not None
    assert inferred["nivel"] == "baja"


def test_high_consumption_inference_preselects_only_unassigned_invoice():
    with conexion_pruebas(row_factory=dict_row) as conn:
        invoice_id = conn.execute(
            """
            INSERT INTO core.facturas (
                sucursal_id, archivo_url, archivo_nombre, archivo_mime,
                archivo_sha256, creada_por
            )
            SELECT id, 'pytest://consumo', 'consumo.txt', 'text/plain', %s, 'pytest-consumo'
            FROM catalog.sucursales WHERE clave = 'POR-ASIGNAR'
            RETURNING id
            """,
            ("c" * 64,),
        ).fetchone()["id"]

        inferred = apply_detected_branch(
            conn, invoice_id, "FILETE COSTILLA TORERITA SIRLOIN"
        )
        branch = conn.execute(
            """
            SELECT s.clave, f.sucursal_origen FROM core.facturas f
            JOIN catalog.sucursales s ON s.id = f.sucursal_id WHERE f.id = %s
            """,
            (invoice_id,),
        ).fetchone()
        conn.rollback()

    assert inferred is not None and inferred["aplicada"] is True
    assert branch["clave"] == "DEMO-A"
    assert branch["sucursal_origen"] == "inferencia_consumo"


def test_ocr_pipeline_persists_consumption_evidence_for_review():
    text = """
    FACTURA
    PROVEEDOR: PROVEEDOR FICTICIO ALFA
    FECHA: 01/08/2026
    SUBTOTAL 100.00
    IVA 16.00
    TOTAL 116.00
    FILETE
    COSTILLA
    TORERITA
    SIRLOIN
    """
    document = OcrDocument(
        text=text, lines=[], confidence=0.95, raw={},
        provider="pytest", model="synthetic", duration_ms=1,
    )
    with conexion_pruebas(row_factory=dict_row) as conn:
        invoice_id = conn.execute(
            """
            INSERT INTO core.facturas (
                sucursal_id, estado, archivo_url, archivo_nombre, archivo_mime,
                archivo_sha256, creada_por
            )
            SELECT id, 'ocr_procesando', 'pytest://ocr-consumo', 'proveedor-demo-a.txt',
                   'text/plain', %s, 'pytest-consumo'
            FROM catalog.sucursales WHERE clave = 'POR-ASIGNAR'
            RETURNING id
            """,
            ("d" * 64,),
        ).fetchone()["id"]

        persist_ocr_result(conn, invoice_id, document)
        result = conn.execute(
            """
            SELECT s.clave, f.sucursal_deteccion, ai.aplicada
            FROM core.facturas f
            JOIN catalog.sucursales s ON s.id = f.sucursal_id
            JOIN audit.inferencias_sucursal ai ON ai.factura_id = f.id
            WHERE f.id = %s
            """,
            (invoice_id,),
        ).fetchone()
        conn.rollback()

    assert result["clave"] == "DEMO-A"
    assert result["sucursal_deteccion"]["metodo"] == "consumo"
    assert result["sucursal_deteccion"]["nivel"] == "alta"
    assert result["aplicada"] is True
