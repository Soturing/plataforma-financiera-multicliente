"""Registro de eventos con ID de correlación (roadmap §3.7.5, hallazgo 12 de la auditoría).

Cada petición lleva un `peticion_id` (el `X-Request-ID` que mande el proxy, si es válido, o uno
nuevo). Aparece en todos los renglones del registro de esa petición, en la respuesta y en la
bitácora de seguridad (`peticion_id`), así que un error se sigue de punta a punta.

Con `FACTURAS_LOG_JSON=true` cada renglón es un objeto JSON (servidor); si no, texto legible (desarrollo).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

peticion_id: ContextVar[str | None] = ContextVar("peticion_id", default=None)

_VALIDO = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_RESERVADOS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def nuevo_peticion_id(entrante: str | None) -> str:
    """El ID del proxy si tiene forma segura (sin espacios ni saltos de línea); si no, uno nuevo."""
    return entrante if entrante and _VALIDO.match(entrante) else uuid.uuid4().hex


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        if pid := peticion_id.get():
            datos["peticion_id"] = pid
        for clave, valor in record.__dict__.items():  # campos añadidos con `extra={...}`
            if clave not in _RESERVADOS and not clave.startswith("_"):
                datos[clave] = valor
        if record.exc_info:
            datos["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


class FormatoTexto(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        texto = super().format(record)
        pid = peticion_id.get()
        return f"{texto} [{pid}]" if pid else texto


def configurar(json_activo: bool = False, nivel: int = logging.INFO) -> None:
    """Deja un solo manejador en el logger raíz. Idempotente: llamarlo otra vez lo reemplaza."""
    raiz = logging.getLogger()
    for manejador in list(raiz.handlers):
        if getattr(manejador, "_facturas", False):
            raiz.removeHandler(manejador)
    manejador = logging.StreamHandler(sys.stderr)
    manejador._facturas = True  # type: ignore[attr-defined]
    manejador.setFormatter(
        FormatoJson() if json_activo else FormatoTexto("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    raiz.addHandler(manejador)
    raiz.setLevel(nivel)
