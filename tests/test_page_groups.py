from io import BytesIO

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.main import app
from app.page_groups import group_batch_pages
from tests.test_pipeline_api import cleanup_test_invoices, one_page_pdf
from apoyo_db import conexion_pruebas

client = TestClient(app)
BATCH_NAME = "pytest-grupo.pdf"


def new_batch(conn):
    return conn.execute(
        """
        INSERT INTO core.lotes_carga (
            sucursal_id, archivo_original_url, archivo_original_nombre, archivo_sha256, total_paginas, creado_por
        ) SELECT id, 'pytest', %s, repeat('a', 64), 3, 'pytest' FROM catalog.sucursales WHERE clave = 'DEMO-A'
        RETURNING id
        """,
        (BATCH_NAME,),
    ).fetchone()["id"]


def make_batch_invoice(conn, batch_id, page: int, total, folio: str) -> str:
    created = client.post(
        "/api/v1/facturas",
        data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
        files={"archivo": (f"grupo-{page}.pdf", BytesIO(one_page_pdf(f"grupo-{page}")), "application/pdf")},
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]
    body = {
        "proveedor": "Proveedor Ficticio Base", "fecha_emision": "2026-08-07",
        "subtotal": "100", "iva": "0", "total": "100.00", "folio": folio,
    }
    assert client.post(f"/api/v1/facturas/{invoice_id}/procesar-simulado", json=body).status_code == 200
    conn.execute("UPDATE core.facturas SET lote_id = %s, pagina_origen = %s WHERE id = %s", (batch_id, page, invoice_id))
    if total is None:
        conn.execute("UPDATE ai.interpretaciones SET total = NULL WHERE factura_id = %s", (invoice_id,))
    return invoice_id


def cleanup():
    cleanup_test_invoices()
    with conexion_pruebas() as conn:
        conn.execute("DELETE FROM core.lotes_carga WHERE archivo_original_nombre = %s", (BATCH_NAME,))


def queue_ids():
    rows = client.get("/api/v1/revision", params={"limit": 200, "orden": "recientes"}).json()
    return {row["id"] for row in rows}


def test_page_without_total_is_linked_to_the_main_page_and_leaves_the_queue():
    cleanup()
    try:
        with conexion_pruebas(row_factory=dict_row) as conn:
            batch_id = new_batch(conn)
            main_id = make_batch_invoice(conn, batch_id, 1, "100.00", "G-77")
            extra_id = make_batch_invoice(conn, batch_id, 2, None, "G-77")
            other_id = make_batch_invoice(conn, batch_id, 3, None, "OTRO-1")
            conn.commit()

            created = group_batch_pages(conn, batch_id)
            conn.commit()
            assert [(str(item["principal"]), str(item["continuacion"])) for item in created] == [(main_id, extra_id)]
            assert group_batch_pages(conn, batch_id) == []  # idempotente

        ids = queue_ids()
        assert main_id in ids and other_id in ids and extra_id not in ids

        case = client.get(f"/api/v1/facturas/{main_id}/expediente").json()
        related = case["paginas_relacionadas"]
        assert [(item["rol"], item["id"]) for item in related] == [("continuacion", extra_id)]
        assert any(v["codigo"] == "PAGINAS_RELACIONADAS" for v in case["validaciones"])

        link_id = related[0]["vinculo_id"]
        separated = client.post(f"/api/v1/continuaciones/{link_id}/separar", json={"separado_por": "pytest"})
        assert separated.status_code == 200, separated.text
        assert extra_id in queue_ids()

        with conexion_pruebas(row_factory=dict_row) as conn:
            assert group_batch_pages(conn, batch_id) == []  # lo separado a mano no se vuelve a ligar
        again = client.post(f"/api/v1/continuaciones/{link_id}/separar", json={"separado_por": "x"})
        assert again.status_code == 404
    finally:
        cleanup()


def test_pages_with_totals_on_both_sides_are_not_grouped():
    cleanup()
    try:
        with conexion_pruebas(row_factory=dict_row) as conn:
            batch_id = new_batch(conn)
            make_batch_invoice(conn, batch_id, 1, "100.00", "G-88")
            make_batch_invoice(conn, batch_id, 2, "100.00", "G-88")
            conn.commit()
            assert group_batch_pages(conn, batch_id) == []
    finally:
        cleanup()
