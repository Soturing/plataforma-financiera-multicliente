from collections.abc import Iterator
from contextvars import ContextVar
from functools import lru_cache
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.config import get_settings

# Alcance de sucursales de la operación en curso (fase 5, RLS): "*" = todas, o UUID
# de catalog.sucursales separados por coma. Lo fija la autorización de cada
# petición; los procesos del sistema (workers OCR) trabajan con todas.
sucursales_actuales: ContextVar[str] = ContextVar("sucursales_actuales", default="*")
# Identidad estable (UUID del plano de control) de quien opera la petición. La base la copia junto
# a cada columna `*_por` (migración 035); sin sesión (workers, modo abierto) queda vacía.
identidad_actual: ContextVar[str | None] = ContextVar("identidad_actual", default=None)


def conectar(database_url: str | None = None, *, sucursales: str | None = None, **kwargs) -> Connection:
    """Abre una conexión a la base del cliente declarando tenant y alcance (D-024).

    Las políticas RLS de la base sólo muestran filas si `app.tenant` coincide con
    la identidad de la base y la sucursal está en `app.sucursales`.
    """
    settings = get_settings()
    alcance = sucursales if sucursales is not None else sucursales_actuales.get()
    if any(c.isspace() for c in settings.tenant_clave + alcance):
        raise ValueError("Tenant o alcance inválido")
    opciones = f"-c app.tenant={settings.tenant_clave} -c app.sucursales={alcance or 'ninguna'}"
    if identidad := identidad_actual.get():
        opciones += f" -c app.identidad={UUID(identidad)}"
    return psycopg.connect(database_url or settings.database_url, options=opciones, **kwargs)


@lru_cache
def rls_verificado() -> bool:
    """¿La base aplica RLS por tenant y sucursal a esta cuenta? Se comprueba en la base,
    no en la configuración: sin RLS efectivo, los consolidados se siguen bloqueando."""
    try:
        with conectar(sucursales="*") as conn:
            fila = conn.execute(
                """SELECT NOT r.rolsuper AND NOT r.rolbypassrls AS sin_privilegios,
                          to_regclass('seguridad.identidad_tenant') IS NOT NULL AS hay_identidad,
                          (SELECT c.relforcerowsecurity FROM pg_class c WHERE c.oid = 'core.facturas'::regclass) AS forzado
                   FROM pg_roles r WHERE r.rolname = current_user"""
            ).fetchone()
            if not (fila[0] and fila[1] and fila[2]):
                return False
            return bool(conn.execute("SELECT seguridad.tenant_correcto()").fetchone()[0])
    except psycopg.Error:
        return False


def get_connection() -> Iterator[Connection]:
    with conectar(row_factory=dict_row) as connection:
        yield connection
