"""Prueba manual de punta a punta con PaddleOCR real."""

import time
from io import BytesIO
from pathlib import Path

import fitz
import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


ACTOR = "ocr-smoke"


def create_invoice_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    lines = [
        "FACTURA DEMO",
        "PROVEEDOR: Proveedor Ficticio Base",
        "RFC: PDA010101AA1",
        "FECHA: 07/08/2026",
        "SUBTOTAL: $10,000.00",
        "IVA: $1,600.00",
        "TOTAL: $11,600.00",
    ]
    for index, line in enumerate(lines):
        page.insert_text((65, 90 + index * 70), line, fontsize=22)
    return document.tobytes()


def cleanup() -> None:
    paths: list[str] = []
    with psycopg.connect(get_settings().database_url) as conn:
        paths += [
            row[0]
            for row in conn.execute(
                """
                SELECT archivo_url FROM core.facturas
                WHERE lote_id IN (SELECT id FROM core.lotes_carga WHERE creado_por = %s)
                """,
                (ACTOR,),
            ).fetchall()
        ]
        paths += [
            row[0]
            for row in conn.execute(
                "SELECT archivo_original_url FROM core.lotes_carga WHERE creado_por = %s",
                (ACTOR,),
            ).fetchall()
        ]
        conn.execute(
            "DELETE FROM core.facturas WHERE lote_id IN (SELECT id FROM core.lotes_carga WHERE creado_por = %s)",
            (ACTOR,),
        )
        conn.execute("DELETE FROM core.lotes_carga WHERE creado_por = %s", (ACTOR,))
    upload_root = get_settings().upload_dir.resolve()
    for raw_path in paths:
        path = Path(raw_path)
        parent = path.parent
        path.unlink(missing_ok=True)
        if parent != upload_root and parent.exists() and not any(parent.iterdir()):
            try:
                parent.rmdir()
            except OSError:
                # OneDrive o un antivirus pueden conservar temporalmente el handle.
                pass


def main() -> None:
    cleanup()
    client = TestClient(app)
    try:
        uploaded = client.post(
            "/api/v1/lotes",
            data={"sucursal_clave": "DEMO-01", "creada_por": ACTOR},
            files={"archivo": ("factura-ocr-real.pdf", BytesIO(create_invoice_pdf()), "application/pdf")},
        )
        uploaded.raise_for_status()
        batch_id = uploaded.json()["id"]
        started = client.post(f"/api/v1/lotes/{batch_id}/procesar")
        started.raise_for_status()

        deadline = time.monotonic() + 240
        state = None
        while time.monotonic() < deadline:
            batches = client.get("/api/v1/lotes").json()
            batch = next(item for item in batches if item["id"] == batch_id)
            if batch["revision"] == 1:
                state = "requiere_revision"
                break
            if batch["errores"] == 1:
                state = "error"
                break
            time.sleep(2)
        if state != "requiere_revision":
            raise RuntimeError(f"OCR no terminó correctamente: {state or 'timeout'}")

        queue = client.get("/api/v1/revision").json()
        invoice = next(item for item in queue if item["archivo_nombre"].startswith("factura-ocr-real.pdf"))
        case = client.get(f"/api/v1/facturas/{invoice['id']}/expediente").json()
        with psycopg.connect(get_settings().database_url) as conn:
            raw_text = conn.execute(
                "SELECT texto_raw FROM ocr.resultados WHERE factura_id = %s",
                (invoice["id"],),
            ).fetchone()[0]
        print(
            {
                "status": "ocr_smoke_ok",
                "provider": case["factura"]["proveedor"],
                "date": case["factura"]["fecha_emision"],
                "subtotal": case["factura"]["subtotal"],
                "iva": case["factura"]["iva"],
                "total": case["factura"]["total"],
                "text": raw_text,
            }
        )
    finally:
        cleanup()


if __name__ == "__main__":
    main()
