from datetime import date
from decimal import Decimal
from io import BytesIO

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.main import app
from app.ocr_processing import find_possible_duplicates
from tests.test_pipeline_api import cleanup_test_invoices, one_page_pdf
from apoyo_db import conexion_pruebas

client = TestClient(app)


def create_processed_invoice(index: int, total: str, issue_date: str, folio: str | None):
    created = client.post(
        "/api/v1/facturas",
        data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
        files={"archivo": (f"dup-{index}.pdf", BytesIO(one_page_pdf(f"dup-{index}")), "application/pdf")},
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]
    body = {
        "proveedor": "Proveedor Ficticio Base", "fecha_emision": issue_date,
        "subtotal": total, "iva": "0", "total": total,
    }
    if folio:
        body["folio"] = folio
    assert client.post(f"/api/v1/facturas/{invoice_id}/procesar-simulado", json=body).status_code == 200
    return invoice_id


def lookup(conn, invoice_id, total, issue_date, folio, folio_origin):
    provider_id = conn.execute(
        "SELECT proveedor_id FROM ai.interpretaciones WHERE factura_id = %s", (invoice_id,)
    ).fetchone()["proveedor_id"]
    return find_possible_duplicates(
        conn, invoice_id, provider_id=provider_id, total=Decimal(total),
        issue_date=issue_date, folio=folio, folio_origin=folio_origin,
    )


def test_same_provider_total_and_close_date_is_flagged_but_far_dates_are_not():
    cleanup_test_invoices()
    try:
        first = create_processed_invoice(1, "777.77", "2026-08-07", "T-1")
        second = create_processed_invoice(2, "777.77", "2026-08-08", "F-9")
        far = create_processed_invoice(3, "777.77", "2026-02-01", "F-10")
        with conexion_pruebas(row_factory=dict_row) as conn:
            found = lookup(conn, second, "777.77", date(2026, 8, 8), "F-9", "detectado")
            assert [item["factura_id"] for item in found if str(item["factura_id"]) == first] != []
            assert all(str(item["factura_id"]) != far for item in found)
            assert lookup(conn, second, "12.00", date(2026, 8, 8), None, "fecha") == []
    finally:
        cleanup_test_invoices()


def test_same_detected_folio_is_flagged_as_continuation_or_duplicate():
    cleanup_test_invoices()
    try:
        first = create_processed_invoice(1, "100.00", "2026-08-07", "A-55")
        second = create_processed_invoice(2, "250.00", "2026-08-20", "A-55")
        with conexion_pruebas(row_factory=dict_row) as conn:
            found = lookup(conn, second, "250.00", date(2026, 8, 20), "A-55", "detectado")
            assert any(str(item["factura_id"]) == first and item["motivo"] == "folio" for item in found)
            # Un folio inventado desde la fecha nunca cuenta como coincidencia.
            assert not any(item["motivo"] == "folio" for item in lookup(conn, second, "250.00", date(2026, 8, 20), "20082026", "fecha"))
    finally:
        cleanup_test_invoices()
