"""Cuotas por cliente (roadmap §3.6.7): un cliente no debe llenar el disco ni inundar la cola.

- Documentos por día: ventana deslizante de 24 h en memoria. Se reinicia con la app; es un tope contra
  un script desbocado, no una contabilidad. El volumen esperado (24 000 por semana) está muy por debajo.
- Almacenamiento: tamaño del directorio de archivos del cliente, recalculado como mucho cada minuto y
  sumando lo que se sube entre cálculos. Aviso en el registro al pasar de 80 %.

Ambos topes se ajustan por cliente (`FACTURAS_CUOTA_DOCUMENTOS_DIA`, `FACTURAS_CUOTA_ALMACENAMIENTO_MB`); 0 los apaga.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from app.config import Settings
from app.errors import DomainError
from app.limite_tasa import LimitadorVentana

log = logging.getLogger("facturas.cuota")

_CADA = 60.0  # segundos entre recálculos del tamaño del directorio
_documentos: dict[int, LimitadorVentana] = {}
_uso = {"directorio": None, "bytes": 0, "calculado": 0.0, "avisado": False}
_cerrojo = threading.Lock()


def verificar_documentos(settings: Settings) -> None:
    """Cuenta un documento nuevo; 429 si el cliente ya agotó su tope de las últimas 24 h."""
    maximo = settings.cuota_documentos_dia
    if maximo <= 0:
        return
    limitador = _documentos.setdefault(maximo, LimitadorVentana(maximo, ventana=24 * 3600))
    permitido, _ = limitador.permitir("documentos")
    if not permitido:
        raise DomainError("Se alcanzó el límite diario de documentos de este cliente. Contacta a soporte.", 429)


def _tamano_directorio(raiz: Path) -> int:
    total = 0
    for carpeta, _, archivos in os.walk(raiz):
        for nombre in archivos:
            try:
                total += os.lstat(os.path.join(carpeta, nombre)).st_size
            except OSError:
                pass
    return total


def espacio_usado(raiz: Path, ahora: float | None = None) -> int:
    ahora = time.monotonic() if ahora is None else ahora
    with _cerrojo:
        if _uso["directorio"] != str(raiz) or ahora - _uso["calculado"] >= _CADA:
            _uso.update(directorio=str(raiz), bytes=_tamano_directorio(raiz), calculado=ahora)
        return _uso["bytes"]


def verificar_almacenamiento(settings: Settings, entrante: int = 0) -> None:
    """507 si guardar `entrante` bytes más superaría la cuota de almacenamiento del cliente."""
    tope = settings.cuota_almacenamiento_mb * 1024 * 1024
    if tope <= 0:
        return
    usado = espacio_usado(settings.upload_dir)
    if usado + entrante > tope:
        raise DomainError("Se alcanzó la cuota de almacenamiento de este cliente. Contacta a soporte.", 507)
    if usado + entrante > 0.8 * tope and not _uso["avisado"]:
        _uso["avisado"] = True
        log.warning("Almacenamiento al %d %% de la cuota (%d MB de %d MB)", 100 * (usado + entrante) // tope,
                    (usado + entrante) // (1024 * 1024), settings.cuota_almacenamiento_mb)


def registrar_subida(tamano: int) -> None:
    """Suma lo recién guardado al uso calculado, para no esperar al siguiente recálculo."""
    with _cerrojo:
        _uso["bytes"] += tamano


def reiniciar() -> None:
    """Para pruebas."""
    with _cerrojo:
        _documentos.clear()
        _uso.update(directorio=None, bytes=0, calculado=0.0, avisado=False)
