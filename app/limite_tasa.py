"""Límite de peticiones por cliente (roadmap §3.6.7, hallazgo 6 de la auditoría).

Ventana deslizante en memoria, por proceso. La app corre en un solo proceso por cliente,
así que basta; si algún día corren varios, el límite se aplica por proceso (más laxo, no
más estricto). No sustituye a un WAF: frena abuso accidental y fuerza bruta simple.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable

MAX_CLAVES = 10_000


class LimitadorVentana:
    def __init__(self, maximo: int, ventana: float = 60.0, reloj: Callable[[], float] = time.monotonic):
        self.maximo = maximo
        self.ventana = ventana
        self._reloj = reloj
        self._golpes: dict[str, deque[float]] = {}

    def permitir(self, clave: str) -> tuple[bool, int]:
        """Devuelve (permitido, segundos para reintentar)."""
        ahora = self._reloj()
        golpes = self._golpes.setdefault(clave, deque())
        while golpes and ahora - golpes[0] >= self.ventana:
            golpes.popleft()
        if len(golpes) >= self.maximo:
            return False, max(1, int(self.ventana - (ahora - golpes[0])) + 1)
        golpes.append(ahora)
        if len(self._golpes) > MAX_CLAVES:
            self._limpiar(ahora)
        return True, 0

    def _limpiar(self, ahora: float) -> None:
        for clave in [c for c, g in self._golpes.items() if not g or ahora - g[-1] >= self.ventana]:
            del self._golpes[clave]


def ip_del_cliente(cliente: str | None, reenviado: str | None, proxy_confiable: bool) -> str:
    """IP para el límite. Tras el proxy propio se usa la última entrada de X-Forwarded-For
    (la que añadió Caddy); sin proxy confiable se ignora la cabecera, que el cliente controla."""
    if proxy_confiable and reenviado:
        ultima = reenviado.split(",")[-1].strip()
        if ultima:
            return ultima
    return cliente or "desconocido"
