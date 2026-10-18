import threading
from collections import Counter
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.main import app
from app.ocr.base import OcrDocument
from app.ocr_queue import (
    PRIORITY_BATCH,
    PRIORITY_INTERACTIVE,
    claim_next,
    complete_job,
    enqueue_invoices,
    fail_job,
    queue_status,
    recover_stale,
    run_worker,
)
from app.repository import cancel_batch, create_invoice
from apoyo_db import conexion_pruebas

ACTOR = "pytest-queue"
TEXT = "FACTURA\nPROVEEDOR DEMO SA DE CV\nRFC AAA010101AAA\nFecha 15/03/2026\nSubtotal 100.00\nIVA 16.00\nTotal 116.00"


class FakeEngine:
    """Motor que no lee archivos: devuelve un texto fijo y puede fallar a propósito."""

    def __init__(self, failures: list[BaseException] | None = None, delay: float = 0.0):
        self.failures = list(failures or [])
        self.delay = delay
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def read(self, path: str) -> OcrDocument:
        with self._lock:
            self.calls.append(path)
            failure = self.failures.pop(0) if self.failures else None
        if self.delay:
            threading.Event().wait(self.delay)
        if failure:
            raise failure
        return OcrDocument(
            text=TEXT, lines=[], confidence=0.9,
            raw={"source": "fake", "pages": []},
            provider="fake", model="fake", duration_ms=1,
        )


@pytest.fixture
def db():
    with conexion_pruebas(row_factory=dict_row) as conn:
        _cleanup(conn)
        conn.commit()
        yield conn
        conn.rollback()
        _cleanup(conn)
        conn.commit()


def _cleanup(conn):
    conn.execute(
        "DELETE FROM core.documentos_duplicados WHERE factura_original_id IN "
        "(SELECT id FROM core.facturas WHERE creada_por = %s) OR factura_duplicada_id IN "
        "(SELECT id FROM core.facturas WHERE creada_por = %s)",
        (ACTOR, ACTOR),
    )
    conn.execute("DELETE FROM core.facturas WHERE creada_por = %s", (ACTOR,))
    conn.execute("DELETE FROM core.lotes_carga WHERE creado_por = %s", (ACTOR,))
    conn.execute("DELETE FROM core.workers_ocr WHERE id LIKE 'pytest-%'")


def make_invoices(conn, count: int) -> list:
    ids = []
    for index in range(count):
        row = create_invoice(
            conn,
            sucursal_clave="DEMO-A",
            filename=f"cola-{index}.pdf",
            mime="application/pdf",
            file_path=f"pytest://cola/{uuid4()}",
            sha256=uuid4().hex + uuid4().hex,
            created_by=ACTOR,
        )
        ids.append(row["id"])
    conn.commit()
    return ids


def state_of(conn, invoice_id) -> str:
    return conn.execute("SELECT estado::text AS e FROM core.facturas WHERE id = %s", (invoice_id,)).fetchone()["e"]


def job_of(conn, invoice_id) -> dict:
    return conn.execute(
        "SELECT * FROM core.trabajos_ocr WHERE factura_id = %s ORDER BY id DESC LIMIT 1", (invoice_id,)
    ).fetchone()


def worker_conn():
    return conexion_pruebas(autocommit=True, row_factory=dict_row)


def drain(engine, **kwargs) -> int:
    return run_worker(
        get_settings().database_url, drain=True, engine=engine,
        worker_id=f"pytest-{uuid4().hex[:6]}", backoff_seconds=0, **kwargs,
    )


def test_enqueue_is_idempotent_and_ignores_finished_invoices(db):
    ids = make_invoices(db, 2)
    assert enqueue_invoices(db, ids, priority=PRIORITY_BATCH) == 2
    assert enqueue_invoices(db, ids, priority=PRIORITY_BATCH) == 0
    db.execute("UPDATE core.facturas SET estado = 'aprobada' WHERE id = %s", (ids[0],))
    db.execute("UPDATE core.trabajos_ocr SET estado = 'cancelado', terminado_en = now() WHERE factura_id = %s", (ids[0],))
    assert enqueue_invoices(db, ids, priority=PRIORITY_BATCH) == 0
    db.commit()
    assert db.execute("SELECT count(*) AS n FROM core.trabajos_ocr WHERE factura_id = ANY(%s)", (ids,)).fetchone()["n"] == 2


def test_worker_processes_every_job_to_review(db):
    ids = make_invoices(db, 3)
    enqueue_invoices(db, ids, priority=PRIORITY_BATCH)
    db.commit()
    engine = FakeEngine()

    assert drain(engine) >= 3

    for invoice_id in ids:
        assert state_of(db, invoice_id) == "requiere_revision"
        job = job_of(db, invoice_id)
        assert job["estado"] == "completado" and job["intentos"] == 1 and job["reservado_por"] is None
        assert db.execute("SELECT count(*) AS n FROM ocr.resultados WHERE factura_id = %s", (invoice_id,)).fetchone()["n"] == 1


def test_interactive_jobs_jump_ahead_of_batch_jobs(db):
    batch_ids = make_invoices(db, 2)
    enqueue_invoices(db, batch_ids, priority=PRIORITY_BATCH)
    db.commit()
    urgent = make_invoices(db, 1)
    enqueue_invoices(db, urgent, priority=PRIORITY_INTERACTIVE)
    db.commit()

    with worker_conn() as conn:
        first = claim_next(conn, "pytest-order", 60)
    assert first["factura_id"] == urgent[0]


def test_concurrent_workers_never_read_the_same_document_twice(db):
    ids = make_invoices(db, 12)
    enqueue_invoices(db, ids, priority=PRIORITY_BATCH)
    db.commit()
    engine = FakeEngine(delay=0.05)

    threads = [threading.Thread(target=drain, args=(engine,)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(engine.calls) == 12
    assert max(Counter(engine.calls).values()) == 1
    assert Counter(state_of(db, invoice_id) for invoice_id in ids) == {"requiere_revision": 12}


def test_transient_error_is_retried_then_succeeds(db):
    (invoice_id,) = make_invoices(db, 1)
    enqueue_invoices(db, [invoice_id], priority=PRIORITY_BATCH)
    db.commit()
    engine = FakeEngine(failures=[RuntimeError("sin memoria")])

    drain(engine)

    job = job_of(db, invoice_id)
    assert job["estado"] == "completado" and job["intentos"] == 2
    assert state_of(db, invoice_id) == "requiere_revision"
    assert len(engine.calls) == 2


def test_permanent_error_fails_immediately_without_retries(db):
    (invoice_id,) = make_invoices(db, 1)
    enqueue_invoices(db, [invoice_id], priority=PRIORITY_BATCH)
    db.commit()
    engine = FakeEngine(failures=[ValueError("El PDF está protegido con contraseña")])

    drain(engine)

    job = job_of(db, invoice_id)
    assert job["estado"] == "fallido" and job["intentos"] == 1
    assert "contraseña" in job["ultimo_error"]
    invoice = db.execute(
        "SELECT estado::text AS e, error_codigo, error_detalle FROM core.facturas WHERE id = %s", (invoice_id,)
    ).fetchone()
    assert (invoice["e"], invoice["error_codigo"]) == ("error", "OCR_ERROR")
    assert len(engine.calls) == 1


def test_retries_stop_after_max_attempts(db):
    (invoice_id,) = make_invoices(db, 1)
    enqueue_invoices(db, [invoice_id], priority=PRIORITY_BATCH, max_attempts=2)
    db.commit()
    engine = FakeEngine(failures=[RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])

    drain(engine)

    job = job_of(db, invoice_id)
    assert job["estado"] == "fallido" and job["intentos"] == 2
    assert state_of(db, invoice_id) == "error"
    # Un fallo definitivo puede reintentarse a mano: vuelve a la cola.
    assert enqueue_invoices(db, [invoice_id], priority=PRIORITY_INTERACTIVE) == 1


def test_expired_lease_returns_job_to_queue_and_exhausted_job_fails(db):
    first, second = make_invoices(db, 2)
    enqueue_invoices(db, [first], priority=PRIORITY_BATCH)
    enqueue_invoices(db, [second], priority=PRIORITY_BATCH, max_attempts=1)
    db.commit()

    with worker_conn() as conn:
        claim_next(conn, "pytest-dead", 60)
        claim_next(conn, "pytest-dead", 60)
        conn.execute("UPDATE core.trabajos_ocr SET reservado_hasta = now() - interval '1 minute' WHERE reservado_por = 'pytest-dead'")
        assert recover_stale(conn) == 2

    assert job_of(db, first)["estado"] == "en_cola" and state_of(db, first) == "recibida"
    assert job_of(db, second)["estado"] == "fallido" and state_of(db, second) == "error"


def test_late_result_from_a_dead_worker_is_discarded(db):
    (invoice_id,) = make_invoices(db, 1)
    enqueue_invoices(db, [invoice_id], priority=PRIORITY_BATCH)
    db.commit()

    with worker_conn() as slow, worker_conn() as other:
        job = claim_next(slow, "pytest-slow", 60)
        slow.execute("UPDATE core.trabajos_ocr SET reservado_hasta = now() - interval '1 minute' WHERE id = %s", (job["id"],))
        recover_stale(other)
        replacement = claim_next(other, "pytest-fast", 60)
        document = FakeEngine().read("x")

        assert complete_job(slow, job, document) == "reserva_perdida"
        assert fail_job(slow, job, RuntimeError("tarde"), retryable=True) == "reserva_perdida"
        assert complete_job(other, replacement, document) == "completado"

    assert db.execute("SELECT count(*) AS n FROM ocr.resultados WHERE factura_id = %s", (invoice_id,)).fetchone()["n"] == 1


def test_cancelled_batch_jobs_are_not_read(db):
    batch_id = uuid4()
    branch = db.execute("SELECT id FROM catalog.sucursales WHERE clave = 'DEMO-A'").fetchone()["id"]
    db.execute(
        """
        INSERT INTO core.lotes_carga (id, sucursal_id, estado, archivo_original_url, archivo_original_nombre,
                                      archivo_sha256, total_paginas, creado_por)
        VALUES (%s, %s, 'listo', 'pytest://lote', 'lote.pdf', %s, 2, %s)
        """,
        (batch_id, branch, uuid4().hex + uuid4().hex, ACTOR),
    )
    ids = []
    for page in (1, 2):
        ids.append(
            db.execute(
                """
                INSERT INTO core.facturas (sucursal_id, canal, archivo_url, archivo_nombre, archivo_mime,
                                           archivo_sha256, creada_por, lote_id, pagina_origen)
                VALUES (%s, 'carga_masiva', 'pytest://p', %s, 'application/pdf', %s, %s, %s, %s) RETURNING id
                """,
                (branch, f"lote - página {page}", uuid4().hex + uuid4().hex, ACTOR, batch_id, page),
            ).fetchone()["id"]
        )
    enqueue_invoices(db, ids, priority=PRIORITY_BATCH)
    db.commit()

    cancel_batch(db, batch_id, ACTOR)
    db.commit()
    engine = FakeEngine()
    drain(engine)

    assert engine.calls == []
    assert {job_of(db, invoice_id)["estado"] for invoice_id in ids} == {"cancelado"}
    assert {state_of(db, invoice_id) for invoice_id in ids} == {"cancelada"}


def test_invoice_cancelled_while_being_read_discards_the_result(db):
    (invoice_id,) = make_invoices(db, 1)
    enqueue_invoices(db, [invoice_id], priority=PRIORITY_BATCH)
    db.commit()

    with worker_conn() as conn:
        job = claim_next(conn, "pytest-cancel", 60)
        db.execute("UPDATE core.facturas SET estado = 'cancelada' WHERE id = %s", (invoice_id,))
        db.commit()
        assert complete_job(conn, job, FakeEngine().read("x")) == "cancelado"

    assert job_of(db, invoice_id)["estado"] == "cancelado"
    assert db.execute("SELECT count(*) AS n FROM ocr.resultados WHERE factura_id = %s", (invoice_id,)).fetchone()["n"] == 0


def test_status_reports_backlog_workers_and_estimate(db):
    ids = make_invoices(db, 3)
    enqueue_invoices(db, ids, priority=PRIORITY_BATCH)
    db.commit()
    baseline = queue_status(db)
    with worker_conn() as conn:
        conn.execute("INSERT INTO core.workers_ocr (id, pid, host) VALUES ('pytest-live', 1, 'test')")
        job = claim_next(conn, "pytest-live", 60)
        status = queue_status(db)
        assert status["workers_activos"] >= 1
        assert status["procesando"] == baseline["procesando"] + 1
        assert status["en_cola"] == baseline["en_cola"] - 1
        assert status["pendientes"] == baseline["pendientes"]
        complete_job(conn, job, FakeEngine().read("x"))
        db.commit()
        done = queue_status(db)
        assert done["completados_1h"] == baseline["completados_1h"] + 1
        assert done["segundos_por_documento"] is not None


def test_api_enqueues_and_exposes_queue_status(db):
    (invoice_id,) = make_invoices(db, 1)
    client = TestClient(app)

    response = client.post(f"/api/v1/facturas/{invoice_id}/procesar-ocr")
    assert response.status_code == 202
    assert response.json()["estado"] == "en_cola" and response.json()["iniciado"] is True
    # Pedirlo otra vez no duplica el trabajo.
    assert client.post(f"/api/v1/facturas/{invoice_id}/procesar-ocr").json()["iniciado"] is False
    assert db.execute("SELECT count(*) AS n FROM core.trabajos_ocr WHERE factura_id = %s", (invoice_id,)).fetchone()["n"] == 1

    status = client.get("/api/v1/cola-ocr").json()
    assert status["en_cola"] >= 1 and status["pendientes"] >= 1
    assert {"workers_activos", "eta_segundos", "fallidos_24h"} <= set(status)
