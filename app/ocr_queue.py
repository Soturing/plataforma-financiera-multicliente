"""Cola de trabajos OCR sobre PostgreSQL y bucle de los workers.

El API solo encola (`enqueue_*`); los workers permanentes toman trabajos con
`FOR UPDATE SKIP LOCKED`, así que N workers nunca leen el mismo documento. Cada
trabajo lleva una reserva (lease) que un hilo renueva mientras se lee; si el
worker muere, la reserva vence y `recover_stale` devuelve el trabajo a la cola.

Las funciones de toma, cierre y recuperación esperan una conexión con
`autocommit=True` (la del worker) y abren sus propias transacciones. Las de
encolado y estado pueden usarse con la conexión normal del API.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Any, Iterable
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pypdf.errors import PyPdfError

from app.database import conectar
from app.errors import DomainError
from app.ocr_processing import persist_ocr_result

log = logging.getLogger("facturas.ocr_queue")

PRIORITY_INTERACTIVE = 1  # una factura subida a mano: el usuario está esperando
PRIORITY_BULK = 3         # carga masiva de varios archivos
PRIORITY_BATCH = 5        # PDF multipágina separado en un lote

# Estados desde los que una factura puede (re)leerse. 'ocr_procesando' cubre
# facturas atoradas por el esquema anterior, que lanzaba un proceso por archivo.
PROCESSABLE_STATES = ("recibida", "error", "ocr_procesando")

# Errores que no se arreglan reintentando: el archivo está dañado o no existe.
PERMANENT_ERRORS = (ValueError, FileNotFoundError, PermissionError, PyPdfError, DomainError)

WORKER_ALIVE_SECONDS = 30
DEFAULT_LEASE_SECONDS = 120
DEFAULT_BACKOFF_SECONDS = 30.0
MAINTENANCE_EVERY_SECONDS = 30
RETENTION_DAYS = 14


# --------------------------------------------------------------------------
# Encolado y estado (lado API)
# --------------------------------------------------------------------------

def enqueue_invoices(
    conn: Connection,
    invoice_ids: Iterable[UUID],
    *,
    priority: int,
    max_attempts: int = 3,
) -> int:
    """Encola facturas respetando su orden. Es idempotente: una factura con un
    trabajo activo no se duplica. Devuelve cuántos trabajos nuevos se crearon."""
    ids = list(dict.fromkeys(invoice_ids))
    if not ids:
        return 0
    rows = conn.execute(
        """
        INSERT INTO core.trabajos_ocr (factura_id, prioridad, max_intentos)
        SELECT f.id, %s, %s
        FROM core.facturas f
        JOIN unnest(%s::uuid[]) WITH ORDINALITY AS wanted(id, position) ON wanted.id = f.id
        WHERE f.estado IN ('recibida', 'error', 'ocr_procesando')
        ORDER BY wanted.position
        ON CONFLICT (factura_id) WHERE estado IN ('en_cola', 'procesando') DO NOTHING
        RETURNING id
        """,
        (priority, max_attempts, ids),
    ).fetchall()
    return len(rows)


def enqueue_batch(conn: Connection, batch_id: UUID, *, priority: int = PRIORITY_BATCH) -> int:
    ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT f.id
            FROM core.facturas f
            JOIN core.lotes_carga l ON l.id = f.lote_id
            WHERE f.lote_id = %s AND l.estado <> 'cancelado'
              AND f.estado IN ('recibida', 'error', 'ocr_procesando')
            ORDER BY f.pagina_origen
            """,
            (batch_id,),
        ).fetchall()
    ]
    return enqueue_invoices(conn, ids, priority=priority)


def is_batch_active(conn: Connection, batch_id: UUID) -> bool:
    return bool(
        conn.execute(
            """
            SELECT 1
            FROM core.trabajos_ocr t
            JOIN core.facturas f ON f.id = t.factura_id
            WHERE f.lote_id = %s AND t.estado IN ('en_cola', 'procesando')
            LIMIT 1
            """,
            (batch_id,),
        ).fetchone()
    )


def queue_status(conn: Connection) -> dict[str, Any]:
    counts = conn.execute(
        """
        SELECT
            count(*) FILTER (WHERE estado = 'en_cola' AND disponible_en <= now())::integer AS en_cola,
            count(*) FILTER (WHERE estado = 'en_cola' AND disponible_en > now())::integer AS reintentando,
            count(*) FILTER (WHERE estado = 'procesando')::integer AS procesando,
            count(*) FILTER (
                WHERE estado = 'fallido' AND terminado_en > now() - interval '24 hours'
            )::integer AS fallidos_24h,
            count(*) FILTER (
                WHERE estado = 'completado' AND terminado_en > now() - interval '1 hour'
            )::integer AS completados_1h,
            -- Mediana: la carga en frío del modelo (decenas de segundos) no debe
            -- inflar la estimación de todo el resto de la cola.
            percentile_cont(0.5) WITHIN GROUP (
                ORDER BY extract(epoch FROM terminado_en - iniciado_en)
            ) FILTER (
                WHERE estado = 'completado' AND terminado_en > now() - interval '30 minutes'
            ) AS segundos_promedio
        FROM core.trabajos_ocr
        WHERE estado IN ('en_cola', 'procesando') OR terminado_en > now() - interval '24 hours'
        """
    ).fetchone()
    workers = conn.execute(
        """
        SELECT id, pid, host, procesados, trabajo_actual,
               extract(epoch FROM now() - iniciado_en)::integer AS segundos_activo
        FROM core.workers_ocr
        WHERE ultimo_latido > now() - make_interval(secs => %s)
        ORDER BY iniciado_en
        """,
        (WORKER_ALIVE_SECONDS,),
    ).fetchall()
    pending = counts["en_cola"] + counts["reintentando"] + counts["procesando"]
    average = float(counts["segundos_promedio"]) if counts["segundos_promedio"] is not None else None
    eta = None
    if pending and workers and average is not None:
        eta = round(pending * average / len(workers))
    return {
        "en_cola": counts["en_cola"],
        "reintentando": counts["reintentando"],
        "procesando": counts["procesando"],
        "pendientes": pending,
        "fallidos_24h": counts["fallidos_24h"],
        "completados_1h": counts["completados_1h"],
        "segundos_por_documento": round(average, 1) if average is not None else None,
        "eta_segundos": eta,
        "workers_activos": len(workers),
        "workers": workers,
    }


# --------------------------------------------------------------------------
# Toma, cierre y recuperación (lado worker, conexión autocommit)
# --------------------------------------------------------------------------

def _close_job(conn: Connection, job_id: int, state: str, message: str | None) -> None:
    conn.execute(
        """
        UPDATE core.trabajos_ocr
        SET estado = %s, reservado_por = NULL, reservado_hasta = NULL,
            terminado_en = now(), ultimo_error = %s
        WHERE id = %s
        """,
        (state, message, job_id),
    )


def claim_next(conn: Connection, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    """Toma el siguiente trabajo disponible o devuelve None si no hay."""
    while True:
        with conn.transaction():
            job = conn.execute(
                """
                WITH next AS (
                    SELECT id FROM core.trabajos_ocr
                    WHERE estado = 'en_cola' AND disponible_en <= now()
                    ORDER BY prioridad, creado_en, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE core.trabajos_ocr t
                SET estado = 'procesando', reservado_por = %s,
                    reservado_hasta = now() + make_interval(secs => %s),
                    intentos = t.intentos + 1, iniciado_en = now(), terminado_en = NULL
                FROM next
                WHERE t.id = next.id
                RETURNING t.id, t.factura_id, t.intentos, t.max_intentos, t.reservado_por
                """,
                (worker_id, lease_seconds),
            ).fetchone()
            if not job:
                return None
            invoice = conn.execute(
                """
                UPDATE core.facturas
                SET estado = 'ocr_procesando', actualizada_en = now()
                WHERE id = %s AND estado IN ('recibida', 'error', 'ocr_procesando')
                RETURNING archivo_url
                """,
                (job["factura_id"],),
            ).fetchone()
            if invoice:
                return {**job, "archivo_url": invoice["archivo_url"]}
            _close_job(conn, job["id"], "cancelado", "La factura ya no estaba disponible")


def _still_owned(conn: Connection, job: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT estado::text, reservado_por FROM core.trabajos_ocr WHERE id = %s FOR UPDATE",
        (job["id"],),
    ).fetchone()
    return bool(row and row["estado"] == "procesando" and row["reservado_por"] == job["reservado_por"])


def complete_job(conn: Connection, job: dict[str, Any], document: Any) -> str:
    """Guarda el resultado y cierra el trabajo en una sola transacción.

    Devuelve 'completado', 'cancelado' (la factura se canceló o borró mientras
    se leía) o 'reserva_perdida' (otro worker ya recuperó el trabajo)."""
    with conn.transaction():
        if not _still_owned(conn, job):
            return "reserva_perdida"
        invoice = conn.execute(
            "SELECT estado::text FROM core.facturas WHERE id = %s", (job["factura_id"],)
        ).fetchone()
        if not invoice or invoice["estado"] != "ocr_procesando":
            _close_job(conn, job["id"], "cancelado", "La factura ya no estaba disponible")
            return "cancelado"
        persist_ocr_result(conn, job["factura_id"], document)
        _close_job(conn, job["id"], "completado", None)
        return "completado"


def fail_job(
    conn: Connection,
    job: dict[str, Any],
    error: BaseException,
    *,
    retryable: bool,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> str:
    """Reintenta con espera creciente o, agotados los intentos, marca error."""
    message = f"{type(error).__name__}: {error}"[:2000]
    with conn.transaction():
        if not _still_owned(conn, job):
            return "reserva_perdida"
        if retryable and job["intentos"] < job["max_intentos"]:
            delay = backoff_seconds * 2 ** (job["intentos"] - 1)
            conn.execute(
                """
                UPDATE core.trabajos_ocr
                SET estado = 'en_cola', reservado_por = NULL, reservado_hasta = NULL,
                    ultimo_error = %s,
                    disponible_en = now() + (%s::double precision * interval '1 second')
                WHERE id = %s
                """,
                (message, delay, job["id"]),
            )
            conn.execute(
                """
                UPDATE core.facturas SET estado = 'recibida', actualizada_en = now()
                WHERE id = %s AND estado = 'ocr_procesando'
                """,
                (job["factura_id"],),
            )
            return "reintento"
        _close_job(conn, job["id"], "fallido", message)
        conn.execute(
            """
            UPDATE core.facturas
            SET estado = 'error', error_codigo = 'OCR_ERROR', error_detalle = %s,
                actualizada_en = now()
            WHERE id = %s AND estado = 'ocr_procesando'
            """,
            (message, job["factura_id"]),
        )
        return "fallido"


def recover_stale(conn: Connection) -> int:
    """Devuelve a la cola los trabajos cuyo worker dejó de renovar la reserva."""
    with conn.transaction():
        rows = conn.execute(
            """
            UPDATE core.trabajos_ocr
            SET estado = CASE WHEN intentos >= max_intentos
                              THEN 'fallido'::core.estado_trabajo_ocr
                              ELSE 'en_cola'::core.estado_trabajo_ocr END,
                terminado_en = CASE WHEN intentos >= max_intentos THEN now() END,
                reservado_por = NULL, reservado_hasta = NULL,
                disponible_en = now(),
                ultimo_error = 'El worker dejó de responder'
            WHERE estado = 'procesando' AND reservado_hasta < now()
            RETURNING factura_id, estado::text AS estado
            """
        ).fetchall()
        for row in rows:
            failed = row["estado"] == "fallido"
            conn.execute(
                """
                UPDATE core.facturas
                SET estado = CASE WHEN %s THEN 'error'::core.estado_factura
                                  ELSE 'recibida'::core.estado_factura END,
                    error_codigo = CASE WHEN %s THEN 'OCR_ERROR' END,
                    error_detalle = CASE WHEN %s THEN 'El worker dejó de responder tras varios intentos' END,
                    actualizada_en = now()
                WHERE id = %s AND estado = 'ocr_procesando'
                """,
                (failed, failed, failed, row["factura_id"]),
            )
    return len(rows)


def purge_old(conn: Connection, days: int = RETENTION_DAYS) -> None:
    conn.execute(
        """
        DELETE FROM core.trabajos_ocr
        WHERE estado IN ('completado', 'cancelado', 'fallido')
          AND terminado_en < now() - make_interval(days => %s)
        """,
        (days,),
    )
    conn.execute("DELETE FROM core.workers_ocr WHERE ultimo_latido < now() - interval '1 day'")


# --------------------------------------------------------------------------
# Registro de workers
# --------------------------------------------------------------------------

def register_worker(conn: Connection, worker_id: str) -> None:
    conn.execute(
        """
        INSERT INTO core.workers_ocr (id, pid, host) VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET ultimo_latido = now(), iniciado_en = now(), procesados = 0
        """,
        (worker_id, os.getpid(), socket.gethostname()),
    )


def heartbeat(conn: Connection, worker_id: str, current_job: int | None, processed: int) -> None:
    conn.execute(
        """
        UPDATE core.workers_ocr
        SET ultimo_latido = now(), trabajo_actual = %s, procesados = %s
        WHERE id = %s
        """,
        (current_job, processed, worker_id),
    )


def unregister_worker(conn: Connection, worker_id: str) -> None:
    conn.execute("DELETE FROM core.workers_ocr WHERE id = %s", (worker_id,))


class _LeaseKeeper(threading.Thread):
    """Renueva la reserva del trabajo y el latido del worker mientras se lee."""

    def __init__(self, database_url: str, job_id: int, worker_id: str, lease_seconds: int):
        super().__init__(daemon=True, name=f"lease-{job_id}")
        self._database_url = database_url
        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._halt = threading.Event()

    def run(self) -> None:
        # Más frecuente que el margen de WORKER_ALIVE_SECONDS: mientras el modelo
        # carga o una página tarda, el worker debe seguir contando como vivo.
        interval = max(1.0, min(10.0, self._lease_seconds / 3))
        try:
            with conectar(self._database_url, autocommit=True) as conn:
                while not self._halt.wait(interval):
                    renewed = conn.execute(
                        """
                        UPDATE core.trabajos_ocr
                        SET reservado_hasta = now() + make_interval(secs => %s)
                        WHERE id = %s AND reservado_por = %s AND estado = 'procesando'
                        """,
                        (self._lease_seconds, self._job_id, self._worker_id),
                    ).rowcount
                    if not renewed:
                        log.warning("Se perdió la reserva del trabajo %s", self._job_id)
                        return
                    conn.execute(
                        "UPDATE core.workers_ocr SET ultimo_latido = now() WHERE id = %s",
                        (self._worker_id,),
                    )
        except Exception:
            log.exception("No se pudo renovar la reserva del trabajo %s", self._job_id)

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=5)


# --------------------------------------------------------------------------
# Bucle del worker
# --------------------------------------------------------------------------

def _handle_job(
    conn: Connection,
    job: dict[str, Any],
    *,
    database_url: str,
    worker_id: str,
    engine: Any | None,
    lease_seconds: int,
    backoff_seconds: float,
) -> str:
    keeper = _LeaseKeeper(database_url, job["id"], worker_id, lease_seconds)
    keeper.start()
    try:
        if engine is None:
            from app.text_processing import get_text_engine

            engine = get_text_engine()
        document = engine.read(job["archivo_url"])
    except Exception as exc:
        keeper.stop()
        log.warning("Trabajo %s (intento %s) falló al leer: %s", job["id"], job["intentos"], exc)
        return fail_job(
            conn, job, exc,
            retryable=not isinstance(exc, PERMANENT_ERRORS),
            backoff_seconds=backoff_seconds,
        )
    keeper.stop()
    try:
        return complete_job(conn, job, document)
    except Exception as exc:
        log.exception("Trabajo %s: no se pudo guardar el resultado", job["id"])
        return fail_job(
            conn, job, exc,
            retryable=isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)),
            backoff_seconds=backoff_seconds,
        )


def run_worker(
    database_url: str,
    *,
    stop: threading.Event | None = None,
    drain: bool = False,
    engine: Any | None = None,
    worker_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    poll_seconds: float = 2.0,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> int:
    """Procesa trabajos hasta que `stop` se active. Con `drain=True` termina al
    vaciarse la cola (útil en pruebas y tareas programadas). Devuelve cuántos
    trabajos cerró."""
    stop = stop or threading.Event()
    worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"
    handled = 0
    last_maintenance = float("-inf")
    conn: Connection | None = None
    log.info("Worker %s iniciado", worker_id)
    try:
        while not stop.is_set():
            try:
                if conn is None or conn.closed:
                    conn = conectar(database_url, autocommit=True, row_factory=dict_row)
                    register_worker(conn, worker_id)
                if time.monotonic() - last_maintenance >= MAINTENANCE_EVERY_SECONDS:
                    recovered = recover_stale(conn)
                    if recovered:
                        log.warning("%s trabajos recuperados de workers caídos", recovered)
                    purge_old(conn)
                    last_maintenance = time.monotonic()
                job = claim_next(conn, worker_id, lease_seconds)
                if job is None:
                    if drain:
                        break
                    heartbeat(conn, worker_id, None, handled)
                    stop.wait(poll_seconds)
                    continue
                heartbeat(conn, worker_id, job["id"], handled)
                outcome = _handle_job(
                    conn, job,
                    database_url=database_url, worker_id=worker_id, engine=engine,
                    lease_seconds=lease_seconds, backoff_seconds=backoff_seconds,
                )
                handled += 1
                log.info("Trabajo %s: %s", job["id"], outcome)
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                if drain:
                    raise
                log.error("Sin conexión a la base de datos (%s); reintentando en 5 s", exc)
                if conn is not None:
                    conn.close()
                conn = None
                stop.wait(5)
    finally:
        if conn is not None and not conn.closed:
            try:
                unregister_worker(conn, worker_id)
            finally:
                conn.close()
        log.info("Worker %s detenido tras %s trabajos", worker_id, handled)
    return handled
