"""Base de control efímera para las pruebas de seguridad.

Crea `facturas_control_pruebas` en el contenedor del plano de control (perfil
`identidad`), aplica el esquema y apunta la configuración de la app a ella con
la cuenta `control_app`. Sin el contenedor, las pruebas que la usan se omiten.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import get_settings

RAIZ = Path(__file__).resolve().parents[2]
BASE_PRUEBAS = "facturas_control_pruebas"


def _con_base(url: str, base: str) -> str:
    partes = urlparse(url)
    return urlunparse(partes._replace(path=f"/{base}"))


def _urls() -> tuple[str, str] | None:
    owner = os.environ.get("FACTURAS_CONTROL_OWNER_URL")
    app_url = get_settings().control_database_url
    if not owner:
        env = RAIZ / ".env"
        if env.exists():
            for linea in env.read_text(encoding="utf-8").splitlines():
                if linea.startswith("FACTURAS_CONTROL_OWNER_URL="):
                    owner = linea.split("=", 1)[1].strip()
    if not owner or not app_url:
        return None
    return owner, app_url


@pytest.fixture(scope="session")
def base_control():
    urls = _urls()
    if urls is None:
        pytest.skip("Plano de control no configurado (FACTURAS_CONTROL_OWNER_URL)")
    owner, app_url = urls
    try:
        with psycopg.connect(owner, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {BASE_PRUEBAS} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {BASE_PRUEBAS}")
    except psycopg.OperationalError:
        pytest.skip("Base del plano de control no disponible")
    owner_pruebas = _con_base(owner, BASE_PRUEBAS)
    with psycopg.connect(owner_pruebas, autocommit=True) as conn:
        for archivo in sorted((RAIZ / "db/control").glob("*.sql")):
            conn.execute(archivo.read_text(encoding="utf-8"))
    settings = get_settings()
    original = settings.control_database_url
    settings.control_database_url = _con_base(app_url, BASE_PRUEBAS)
    yield {"owner": owner_pruebas, "app": settings.control_database_url}
    settings.control_database_url = original


@pytest.fixture
def owner(base_control):
    with psycopg.connect(base_control["owner"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def control_app(base_control):
    with psycopg.connect(base_control["app"], row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def tenant(base_control):
    """Tenant del data plane actual: dos restaurantes, tres sucursales sintéticas."""
    clave = get_settings().tenant_clave
    with psycopg.connect(base_control["app"], row_factory=dict_row) as conn:
        t = conn.execute(
            """INSERT INTO control.tenants (clave, nombre, data_plane_url) VALUES (%s, 'Grupo de prueba', 'http://prueba')
               ON CONFLICT (clave) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING *""",
            (clave,),
        ).fetchone()
        for rest in ("REST-UNO", "REST-DOS"):
            conn.execute(
                """INSERT INTO control.restaurantes (tenant_id, clave, nombre, data_plane_id) VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (t["id"], rest, f"Restaurante {rest}", uuid4()),
            )
        for suc, rest in (("NORTE", "REST-UNO"), ("CENTRO", "REST-UNO"), ("SUR", "REST-DOS")):
            conn.execute(
                """INSERT INTO control.sucursales (tenant_id, clave, nombre, data_plane_id, restaurante_clave)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (t["id"], suc, f"Sucursal {suc}", uuid4(), rest),
            )
    return t


class Fabrica:
    """Crea identidades, asignaciones y sesiones directamente en la base de control."""

    def __init__(self, url: str, tenant: dict) -> None:
        self.url = url
        self.tenant = tenant

    def _conn(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def identidad(self, *, estado: str = "ACTIVA") -> dict:
        with self._conn() as conn:
            return conn.execute(
                "INSERT INTO control.identidades (idp_subject, correo, nombre, estado) VALUES (%s, %s, %s, %s) RETURNING *",
                (str(uuid4()), f"prueba-{secrets.token_hex(4)}@demo.test", "Persona de Prueba", estado),
            ).fetchone()

    def asignacion(self, identidad_id: UUID, rol: str, *, tenant: bool = True, **campos) -> dict:
        from app.seguridad.control import guardar_alcance

        with self._conn() as conn:
            fila = conn.execute(
                """INSERT INTO control.asignaciones (identidad_id, rol, tenant_id, modulos, condicionados, motivo)
                   VALUES (%s, %s, %s, %s, %s, 'prueba') RETURNING *""",
                (identidad_id, rol, self.tenant["id"] if tenant else None, campos.get("modulos"),
                 campos.get("condicionados", [])),
            ).fetchone()
            if tenant:
                guardar_alcance(conn, fila["id"], self.tenant["id"], campos.get("restaurantes"), campos.get("sucursales"))
            return fila

    def sesion(self, identidad_id: UUID, asignacion: dict | None, *, llave_fisica: bool = False,
               autenticado_hace: timedelta = timedelta(minutes=1), inactividad=timedelta(minutes=30),
               expira_en=timedelta(hours=8)) -> str:
        from app.seguridad.sesiones import huella

        token = secrets.token_urlsafe(32)
        ahora = datetime.now(timezone.utc)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO control.sesiones (token_hash, identidad_id, asignacion_id, rol_activo, tenant_id,
                       inactividad_max, expira_absoluta, autenticado_en, metodo_auth, llave_fisica)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (huella(token), identidad_id, asignacion["id"] if asignacion else None,
                 asignacion["rol"] if asignacion else None, self.tenant["id"],
                 inactividad, ahora + expira_en, ahora - autenticado_hace,
                 "LLAVE_FISICA" if llave_fisica else "PASSKEY", llave_fisica),
            )
        return token

    def persona(self, rol: str, **kw) -> tuple[dict, dict, str]:
        """Identidad + asignación + sesión con contexto elegido."""
        llave = kw.pop("llave_fisica", rol in ("CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD"))
        autenticado_hace = kw.pop("autenticado_hace", timedelta(minutes=1))
        ident = self.identidad()
        asig = self.asignacion(ident["id"], rol, tenant=rol not in ("CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "SOPORTE_TECNICO"), **kw)
        token = self.sesion(ident["id"], asig, llave_fisica=llave, autenticado_hace=autenticado_hace)
        return ident, asig, token


@pytest.fixture
def fabrica(base_control, tenant):
    return Fabrica(base_control["app"], tenant)
