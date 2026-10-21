"""Antivirus (ClamAV) para los archivos que suben las personas (roadmap §3.6.4, hallazgo 5).

Habla el protocolo de `clamd` por TCP (`INSTREAM`), sin dependencias nuevas. Hay tres modos
(`FACTURAS_ANTIVIRUS_MODO`):

- `apagado`: no escanea (desarrollo local; ClamAV consume ~1 GB de memoria).
- `opcional`: escanea; si el antivirus no responde, avisa en el registro y acepta el archivo.
- `obligatorio`: escanea; si no responde, **rechaza** el archivo (falla cerrada). Es el del servidor.

Un archivo infectado se rechaza siempre y no queda en disco.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from pathlib import Path

from app.config import Settings
from app.errors import DomainError

log = logging.getLogger("facturas.antivirus")

TROZO = 64 * 1024  # clamd acepta trozos de hasta StreamMaxLength; 64 KB es habitual


class AntivirusNoDisponible(RuntimeError):
    pass


def _escanear_flujo(trozos, host: str, puerto: int, timeout: float) -> str | None:
    """Envía los trozos a clamd. Devuelve el nombre de la firma si hay virus, None si está limpio."""
    try:
        with socket.create_connection((host, puerto), timeout=timeout) as conexion:
            conexion.settimeout(timeout)
            conexion.sendall(b"zINSTREAM\0")
            for trozo in trozos:
                conexion.sendall(struct.pack("!I", len(trozo)) + trozo)
            conexion.sendall(struct.pack("!I", 0))
            respuesta = b""
            while not respuesta.endswith(b"\0"):
                parte = conexion.recv(4096)
                if not parte:
                    break
                respuesta += parte
    except OSError as exc:  # sin conexión, tiempo agotado, conexión cortada
        raise AntivirusNoDisponible(f"clamd no respondió: {exc}") from exc
    texto = respuesta.rstrip(b"\0").decode("utf-8", errors="replace").strip()
    if texto.endswith("OK"):
        return None
    if texto.endswith("FOUND"):
        return texto.removeprefix("stream:").removesuffix("FOUND").strip() or "desconocida"
    raise AntivirusNoDisponible(f"Respuesta inesperada de clamd: {texto[:200]!r}")


def _trozos_de_archivo(ruta: Path):
    with ruta.open("rb") as archivo:
        while trozo := archivo.read(TROZO):
            yield trozo


def _trozos_de_bytes(datos: bytes):
    for inicio in range(0, len(datos), TROZO):
        yield datos[inicio:inicio + TROZO]


def _decidir(firma_o_error, settings: Settings, nombre: str) -> None:
    """Aplica el modo: infectado siempre rechaza; si no hay servicio, `obligatorio` rechaza y `opcional` deja pasar."""
    if isinstance(firma_o_error, AntivirusNoDisponible):
        if settings.antivirus_modo == "obligatorio":
            log.error("Antivirus no disponible; se rechaza %s: %s", nombre, firma_o_error)
            raise DomainError("No se pudo verificar el archivo con el antivirus. Intenta de nuevo en unos minutos.", 503)
        log.warning("Antivirus no disponible; se acepta %s sin escanear: %s", nombre, firma_o_error)
        return
    if firma_o_error is not None:
        log.warning("Archivo rechazado por el antivirus: %s (%s)", nombre, firma_o_error)
        raise DomainError("El archivo contiene software malicioso y no se guardó.", 422)


async def escanear_archivo(ruta: Path, settings: Settings) -> None:
    """Escanea un archivo ya guardado. Lanza `DomainError` si hay que rechazarlo."""
    if settings.antivirus_modo == "apagado":
        return
    try:
        resultado = await asyncio.to_thread(
            _escanear_flujo, _trozos_de_archivo(ruta), settings.antivirus_host, settings.antivirus_puerto, settings.antivirus_timeout
        )
    except AntivirusNoDisponible as exc:
        resultado = exc
    _decidir(resultado, settings, ruta.name)


async def escanear_bytes(datos: bytes, settings: Settings, nombre: str = "archivo") -> None:
    """Escanea contenido en memoria (catálogos y archivos de ventas)."""
    if settings.antivirus_modo == "apagado":
        return
    try:
        resultado = await asyncio.to_thread(
            _escanear_flujo, _trozos_de_bytes(datos), settings.antivirus_host, settings.antivirus_puerto, settings.antivirus_timeout
        )
    except AntivirusNoDisponible as exc:
        resultado = exc
    _decidir(resultado, settings, nombre)
