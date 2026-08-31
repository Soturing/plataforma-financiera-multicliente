import subprocess
import sys
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.ocr_processing import claim_batch_invoices, persist_ocr_result
from app.text_processing import get_text_engine


def _process_invoice(invoice_id: UUID, file_path: str) -> None:
    settings = get_settings()
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            started = conn.execute(
                """
                UPDATE core.facturas SET estado = 'ocr_procesando', actualizada_en = now()
                WHERE id = %s AND estado IN ('recibida', 'error') RETURNING id
                """,
                (invoice_id,),
            ).fetchone()
            if not started:
                return
        result = get_text_engine().read(file_path)
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            persist_ocr_result(conn, invoice_id, result)
    except Exception as exc:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            conn.execute(
                """
                UPDATE core.facturas SET estado = 'error', error_codigo = 'OCR_ERROR',
                    error_detalle = %s, actualizada_en = now() WHERE id = %s
                """,
                (str(exc)[:2000], invoice_id),
            )


def _process_batch(batch_id: UUID) -> None:
    settings = get_settings()
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            invoices = claim_batch_invoices(conn, batch_id)
        engine = get_text_engine()
        for invoice in invoices:
            try:
                with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
                    started = conn.execute(
                        """
                        UPDATE core.facturas f
                        SET estado = 'ocr_procesando', actualizada_en = now()
                        FROM core.lotes_carga l
                        WHERE f.id = %s AND f.lote_id = l.id
                          AND l.estado <> 'cancelado'
                          AND f.estado IN ('recibida', 'error', 'ocr_procesando')
                        RETURNING f.id
                        """,
                        (invoice["id"],),
                    ).fetchone()
                    if not started:
                        continue
                result = engine.read(invoice["archivo_url"])
                with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
                    persist_ocr_result(conn, invoice["id"], result)
            except Exception as exc:
                with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
                    conn.execute(
                        """
                        UPDATE core.facturas SET estado = 'error', error_codigo = 'OCR_ERROR',
                            error_detalle = %s, actualizada_en = now() WHERE id = %s
                        """,
                        (str(exc)[:2000], invoice["id"]),
                    )
    finally:
        pass


def start_batch_job(batch_id: UUID) -> bool:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        [sys.executable, "-m", "app.worker_cli", "--batch", str(batch_id)],
        cwd=str(get_settings().upload_dir.resolve().parents[1]),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    return True


def is_batch_active(batch_id: UUID) -> bool:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        return bool(
            conn.execute(
                "SELECT 1 FROM core.facturas WHERE lote_id = %s AND estado = 'ocr_procesando' LIMIT 1",
                (batch_id,),
            ).fetchone()
        )


def start_invoice_job(invoice_id: UUID, file_path: str) -> bool:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        [sys.executable, "-m", "app.worker_cli", "--invoice", str(invoice_id)],
        cwd=str(get_settings().upload_dir.resolve().parents[1]),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    return True
