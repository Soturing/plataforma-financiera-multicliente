"""Migración 035: cada columna *_por guarda también el UUID estable de la identidad que operó."""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

import app.database as database
from app.config import get_settings

ACTOR = "pytest-identidad-035"
ESQUEMAS = ("audit", "catalog", "core", "finance")


def _conexion(identidad: str | None = None) -> psycopg.Connection:
    url = os.environ.get("TENANT_OWNER_URL")
    if not url:
        pytest.skip("Requiere TENANT_OWNER_URL (python -m app.plataforma.tenants pruebas)")
    opciones = f"-c app.tenant={get_settings().tenant_clave} -c app.sucursales=* -c audit.purga=on"
    if identidad is not None:
        opciones += f" -c app.identidad={identidad}"
    return psycopg.connect(url, options=opciones, row_factory=dict_row)


def _insertar_factura(c) -> UUID:
    sucursal = c.execute("SELECT id FROM catalog.sucursales ORDER BY clave LIMIT 1").fetchone()["id"]
    return c.execute(
        """
        INSERT INTO core.facturas (sucursal_id, canal, estado, archivo_url, archivo_nombre, archivo_mime,
                                   archivo_sha256, creada_por)
        VALUES (%s, 'web', 'recibida', 'x', 'x.pdf', 'application/pdf', %s, %s) RETURNING id
        """,
        (sucursal, uuid4().hex + uuid4().hex, ACTOR),
    ).fetchone()["id"]


@pytest.fixture(autouse=True)
def limpiar():
    yield
    with _conexion() as c:
        c.execute("DELETE FROM core.facturas WHERE creada_por = %s", (ACTOR,))


def test_toda_columna_por_tiene_su_id_y_su_trigger():
    """Si alguien añade una columna *_por sin su *_por_id, esta prueba lo avisa."""
    with _conexion() as c:
        columnas = c.execute(
            """
            SELECT c.table_schema AS esquema, c.table_name AS tabla, c.column_name AS columna
            FROM information_schema.columns c
            JOIN information_schema.tables t USING (table_schema, table_name)
            WHERE t.table_type = 'BASE TABLE' AND c.table_schema = ANY(%s)
              AND c.column_name LIKE '%%\\_por' AND c.data_type = 'text'
              AND NOT (c.table_schema = 'core' AND c.table_name = 'trabajos_ocr')
            """,
            (list(ESQUEMAS),),
        ).fetchall()
        assert len(columnas) >= 25
        for col in columnas:
            hermana = c.execute(
                """SELECT data_type FROM information_schema.columns
                   WHERE table_schema = %s AND table_name = %s AND column_name = %s""",
                (col["esquema"], col["tabla"], col["columna"] + "_id"),
            ).fetchone()
            assert hermana and hermana["data_type"] == "uuid", f"Falta {col['columna']}_id en {col['esquema']}.{col['tabla']}"
            trigger = c.execute(
                """SELECT 1 FROM pg_trigger WHERE tgrelid = format('%%I.%%I', %s::text, %s::text)::regclass
                   AND tgname = 'completar_identidad'""",
                (col["esquema"], col["tabla"]),
            ).fetchone()
            assert trigger, f"Falta el trigger completar_identidad en {col['esquema']}.{col['tabla']}"


def test_se_copia_la_identidad_de_la_sesion():
    identidad = str(uuid4())
    with _conexion(identidad) as c:
        factura = _insertar_factura(c)
        fila = c.execute("SELECT creada_por, creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()
        c.commit()
    assert fila["creada_por"] == ACTOR
    assert str(fila["creada_por_id"]) == identidad


def test_sin_sesion_queda_vacia_y_no_se_inventa():
    with _conexion() as c:
        factura = _insertar_factura(c)
        fila = c.execute("SELECT creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()
        c.commit()
    assert fila["creada_por_id"] is None


def test_un_valor_que_no_es_uuid_no_rompe_la_escritura():
    with _conexion("no-es-un-uuid") as c:
        factura = _insertar_factura(c)
        fila = c.execute("SELECT creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()
        c.commit()
    assert fila["creada_por_id"] is None


def test_actualizar_otra_columna_conserva_el_id_y_cambiar_la_etiqueta_lo_renueva():
    primera, segunda = str(uuid4()), str(uuid4())
    with _conexion(primera) as c:
        factura = _insertar_factura(c)
        c.commit()
    with _conexion(segunda) as c:
        c.execute("UPDATE core.facturas SET archivo_nombre = 'otro.pdf' WHERE id = %s", (factura,))
        assert str(c.execute("SELECT creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()["creada_por_id"]) == primera
        c.execute("UPDATE core.facturas SET creada_por = %s WHERE id = %s", (ACTOR, factura))  # misma etiqueta: sin cambio
        assert str(c.execute("SELECT creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()["creada_por_id"]) == primera
        c.execute("UPDATE core.facturas SET creada_por = %s WHERE id = %s", (ACTOR + "-2", factura))
        assert str(c.execute("SELECT creada_por_id FROM core.facturas WHERE id = %s", (factura,)).fetchone()["creada_por_id"]) == segunda
        c.commit()
    with _conexion() as c:
        c.execute("DELETE FROM core.facturas WHERE id = %s", (factura,))


def test_conectar_declara_la_identidad_de_la_peticion(monkeypatch):
    capturado = {}
    monkeypatch.setattr(database.psycopg, "connect", lambda url, **kw: capturado.update(kw) or object())
    identidad = str(uuid4())
    token = database.identidad_actual.set(identidad)
    try:
        database.conectar("postgresql://u:p@127.0.0.1:1/x")
    finally:
        database.identidad_actual.reset(token)
    assert f"-c app.identidad={identidad}" in capturado["options"]
    database.conectar("postgresql://u:p@127.0.0.1:1/x")
    assert "app.identidad" not in capturado["options"]


def test_conectar_rechaza_una_identidad_que_no_es_uuid(monkeypatch):
    monkeypatch.setattr(database.psycopg, "connect", lambda url, **kw: object())
    token = database.identidad_actual.set("1 -c search_path=evil")
    try:
        with pytest.raises(ValueError):
            database.conectar("postgresql://u:p@127.0.0.1:1/x")
    finally:
        database.identidad_actual.reset(token)


def test_tenant_runtime_tiene_topes_de_consulta_y_de_transaccion_ociosa():
    """§3.8.3: los fija `tenants.crear_roles` (alta y base desechable) o `tenants migrar`."""
    with _conexion() as c:
        config = c.execute("SELECT rolconfig FROM pg_roles WHERE rolname = 'tenant_runtime'").fetchone()["rolconfig"] or []
    assert "statement_timeout=120s" in config
    assert "idle_in_transaction_session_timeout=60s" in config
