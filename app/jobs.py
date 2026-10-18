import subprocess
import sys
import time
from pathlib import Path

import psycopg

from app.config import Settings, get_settings
from app.ocr_queue import WORKER_ALIVE_SECONDS

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Evita lanzar un supervisor por cada petición mientras el anterior arranca.
_SPAWN_COOLDOWN_SECONDS = 30
_last_spawn = float("-inf")


def workers_alive(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    with psycopg.connect(settings.database_url) as conn:
        return bool(
            conn.execute(
                """
                SELECT 1 FROM core.workers_ocr
                WHERE ultimo_latido > now() - make_interval(secs => %s)
                LIMIT 1
                """,
                (WORKER_ALIVE_SECONDS,),
            ).fetchone()
        )


def ensure_workers_running(settings: Settings | None = None) -> bool:
    """Lanza el supervisor de workers si nadie está leyendo la cola.

    Es seguro llamarlo en cada encolado: el supervisor toma un candado en la base
    de datos, así que un segundo intento termina de inmediato. Devuelve True si
    lanzó un proceso."""
    global _last_spawn
    settings = settings or get_settings()
    if not settings.ocr_autostart_workers:
        return False
    if time.monotonic() - _last_spawn < _SPAWN_COOLDOWN_SECONDS or workers_alive(settings):
        return False
    _last_spawn = time.monotonic()

    log_dir = PROJECT_ROOT / "tmp"
    log_dir.mkdir(exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with (log_dir / "ocr-worker.log").open("ab") as log_file:
        subprocess.Popen(
            [sys.executable, "-m", "app.worker_cli"],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            creationflags=flags,
        )
    return True
