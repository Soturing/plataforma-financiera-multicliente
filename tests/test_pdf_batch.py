from io import BytesIO
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.config import get_settings
from app.main import app


def make_pdf(page_count: int) -> bytes:
    writer = PdfWriter()
    for index in range(page_count):
        writer.add_blank_page(width=612 + index, height=792)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def cleanup_batches():
    paths: list[str] = []
    with psycopg.connect(get_settings().database_url) as conn:
        rows = conn.execute(
            """
            SELECT f.archivo_url FROM core.facturas f
            JOIN core.lotes_carga l ON l.id = f.lote_id
            WHERE l.creado_por = 'pytest-pdf'
            """
        ).fetchall()
        paths.extend(row[0] for row in rows)
        originals = conn.execute(
            "SELECT archivo_original_url FROM core.lotes_carga WHERE creado_por = 'pytest-pdf'"
        ).fetchall()
        paths.extend(row[0] for row in originals)
        singles = conn.execute(
            "SELECT archivo_url FROM core.facturas WHERE creada_por = 'pytest-pdf' AND lote_id IS NULL"
        ).fetchall()
        paths.extend(row[0] for row in singles)
        conn.execute(
            "DELETE FROM core.facturas WHERE lote_id IN (SELECT id FROM core.lotes_carga WHERE creado_por = 'pytest-pdf')"
        )
        conn.execute("DELETE FROM core.facturas WHERE creada_por = 'pytest-pdf' AND lote_id IS NULL")
        conn.execute("DELETE FROM core.lotes_carga WHERE creado_por = 'pytest-pdf'")
        conn.execute("DELETE FROM audit.documentos_eliminados WHERE eliminado_por = 'pytest-pdf'")
    directories = set()
    for raw_path in paths:
        path = Path(raw_path)
        directories.add(path.parent)
        path.unlink(missing_ok=True)
    upload_root = get_settings().upload_dir.resolve()
    for directory in directories:
        if directory.resolve() != upload_root and directory.exists():
            directory.rmdir()


def test_multipage_pdf_creates_one_invoice_per_page():
    cleanup_batches()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/lotes",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest-pdf"},
            files={"archivo": ("cincuenta-facturas.pdf", make_pdf(3), "application/pdf")},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["total_paginas"] == 3
        assert result["facturas_creadas"] == 3

        batches = client.get("/api/v1/lotes").json()
        batch = next(item for item in batches if item["id"] == result["id"])
        assert batch["recibidas"] == 3

        with psycopg.connect(get_settings().database_url) as conn:
            rows = conn.execute(
                """
                SELECT pagina_origen, archivo_url FROM core.facturas
                WHERE lote_id = %s ORDER BY pagina_origen
                """,
                (result["id"],),
            ).fetchall()
        assert [row[0] for row in rows] == [1, 2, 3]
        assert all(len(PdfReader(row[1]).pages) == 1 for row in rows)
    finally:
        cleanup_batches()


def test_multipage_pdf_cannot_silently_enter_as_one_invoice():
    cleanup_batches()
    client = TestClient(app)
    try:
        rejected = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest-pdf"},
            files={"archivo": ("lote-sin-marcar.pdf", make_pdf(3), "application/pdf")},
        )
        assert rejected.status_code == 409, rejected.text
        assert "3 páginas" in rejected.json()["detail"]

        intentional = client.post(
            "/api/v1/facturas",
            data={
                "sucursal_clave": "DEMO-A",
                "creada_por": "pytest-pdf",
                "permitir_pdf_multipagina": "true",
            },
            files={"archivo": ("factura-multipagina.pdf", make_pdf(2), "application/pdf")},
        )
        assert intentional.status_code == 201, intentional.text
    finally:
        cleanup_batches()


def test_batch_can_be_cancelled_and_selected_documents_deleted():
    cleanup_batches()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/lotes",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest-pdf"},
            files={"archivo": ("lote-equivocado.pdf", make_pdf(3), "application/pdf")},
        )
        assert created.status_code == 201, created.text
        batch_id = created.json()["id"]
        cancelled = client.post(
            f"/api/v1/lotes/{batch_id}/cancelar",
            json={"cancelado_por": "pytest-pdf"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["canceladas"] == 3

        with psycopg.connect(get_settings().database_url) as conn:
            invoices = conn.execute(
                "SELECT id FROM core.facturas WHERE lote_id = %s ORDER BY pagina_origen",
                (batch_id,),
            ).fetchall()
        deleted = client.request(
            "DELETE",
            "/api/v1/facturas",
            json={"factura_ids": [str(row[0]) for row in invoices], "eliminado_por": "pytest-pdf"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["eliminados"] == 3
        assert deleted.json()["archivos_eliminados"] == 4
        with psycopg.connect(get_settings().database_url) as conn:
            assert conn.execute("SELECT count(*) FROM core.facturas WHERE lote_id = %s", (batch_id,)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM core.lotes_carga WHERE id = %s", (batch_id,)).fetchone()[0] == 0
            assert conn.execute(
                "SELECT count(*) FROM audit.documentos_eliminados WHERE eliminado_por = 'pytest-pdf'"
            ).fetchone()[0] == 3
    finally:
        cleanup_batches()
