"""Workers de la cola OCR.

    python -m app.worker_cli                  supervisor: mantiene N workers vivos
    python -m app.worker_cli --procesos 3     supervisor con 3 workers
    python -m app.worker_cli --una-vez        vacía la cola en este proceso y termina
    python -m app.worker_cli --hijo           un solo worker (lo usa el supervisor)

Cada worker es un proceso aparte con su propio modelo cargado una sola vez. El
supervisor reinicia al que muera (por ejemplo por falta de memoria) sin afectar
a los demás; los trabajos de un worker caído vuelven a la cola al vencer su
reserva.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time


from app import registro
from app.config import get_settings
from app.database import conectar
from app.ocr_queue import run_worker

SUPERVISOR_LOCK_KEY = 7_204_001
RESTART_DELAY_SECONDS = 5

log = logging.getLogger("facturas.worker")


def _stop_on_signals(stop: threading.Event) -> None:
    def handler(signum, _frame):
        log.info("Señal %s recibida; terminando al cerrar el trabajo actual", signum)
        stop.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handler)


def _run_single(*, drain: bool) -> int:
    settings = get_settings()
    stop = threading.Event()
    _stop_on_signals(stop)
    handled = run_worker(
        settings.database_url,
        stop=stop,
        drain=drain,
        lease_seconds=settings.ocr_lease_seconds,
    )
    if drain:
        log.info("Cola vacía: %s trabajos cerrados", handled)
    return 0


def _spawn_child() -> subprocess.Popen:
    command = [sys.executable, "-m", "app.worker_cli", "--hijo"]
    if sys.platform == "win32":
        # Prioridad baja: leer documentos nunca debe quitarle CPU a la interfaz
        # cuando comparten servidor.
        return subprocess.Popen(
            command,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )
    return subprocess.Popen(command, preexec_fn=lambda: os.nice(10))


def _terminate(child: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # El python.exe de un entorno virtual es un lanzador que crea el intérprete
        # real como proceso hijo; terminate() solo mataría al lanzador.
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    else:
        child.terminate()


def _supervise(processes: int) -> int:
    settings = get_settings()
    # El candado vive mientras viva esta conexión: solo puede haber un supervisor.
    lock_conn = conectar(settings.database_url, autocommit=True)
    acquired = lock_conn.execute(
        "SELECT pg_try_advisory_lock(%s)", (SUPERVISOR_LOCK_KEY,)
    ).fetchone()[0]
    if not acquired:
        log.info("Ya hay un supervisor de OCR activo; no se inicia otro")
        lock_conn.close()
        return 0

    stop = threading.Event()
    _stop_on_signals(stop)
    children: list[subprocess.Popen | None] = [None] * processes
    next_start = [0.0] * processes
    log.info("Supervisor iniciado con %s worker(s)", processes)
    try:
        while not stop.is_set():
            for slot, child in enumerate(children):
                if child is not None and child.poll() is None:
                    continue
                if child is not None:
                    log.warning("Worker %s terminó con código %s; se reiniciará", slot, child.returncode)
                    children[slot] = None
                    next_start[slot] = time.monotonic() + RESTART_DELAY_SECONDS
                if time.monotonic() >= next_start[slot]:
                    children[slot] = _spawn_child()
            stop.wait(2)
    finally:
        for child in children:
            if child is not None and child.poll() is None:
                _terminate(child)
        for child in children:
            if child is not None:
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
        lock_conn.close()
        log.info("Supervisor detenido")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--una-vez", action="store_true", help="vacía la cola y termina")
    mode.add_argument("--hijo", action="store_true", help="ejecuta un único worker")
    parser.add_argument("--procesos", type=int, help="workers del supervisor (por defecto FACTURAS_OCR_WORKERS)")
    args = parser.parse_args()

    registro.configurar(get_settings().log_json)
    if args.una_vez:
        return _run_single(drain=True)
    if args.hijo:
        return _run_single(drain=False)
    processes = args.procesos or get_settings().ocr_workers
    if processes < 1:
        parser.error("--procesos debe ser al menos 1")
    return _supervise(processes)


if __name__ == "__main__":
    sys.exit(main())
