"""Conexión para preparar y limpiar datos en las pruebas.

La app bajo prueba usa su propia cuenta (tenant_runtime, con RLS). Las pruebas
preparan y limpian datos como propietaria cuando `TENANT_OWNER_URL` está definida
(la exporta `python -m app.plataforma.tenants pruebas`), y siempre declaran el tenant
y el alcance total, para que funcionen igual con o sin RLS.
"""
from __future__ import annotations

import os

import psycopg

from app.config import get_settings


def conexion_pruebas(**kwargs) -> psycopg.Connection:
    settings = get_settings()
    url = os.environ.get("TENANT_OWNER_URL") or settings.database_url
    # audit.purga: la limpieza puede borrar filas de prueba de la auditoría de sólo anexado (034).
    opciones = f"-c app.tenant={settings.tenant_clave} -c app.sucursales=* -c audit.purga=on"
    return psycopg.connect(url, options=opciones, **kwargs)
