"""Red de seguridad de la base (roadmap §3.8.5): las restricciones rechazan lo que deben.

Cada prueba corre en su propia transacción y la deshace: no deja datos. Sólo comprueba reglas que ya
existen en el esquema; si alguien las quita por accidente, estas pruebas fallan.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import errors
from psycopg.rows import dict_row

from app.config import get_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("TENANT_OWNER_URL"), reason="Requiere TENANT_OWNER_URL (python -m app.plataforma.tenants pruebas)"
)


@contextmanager
def _transaccion():
    opciones = f"-c app.tenant={get_settings().tenant_clave} -c app.sucursales=*"
    with psycopg.connect(os.environ["TENANT_OWNER_URL"], options=opciones, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            conn.rollback()


def _sucursal(conn):
    return conn.execute("SELECT id FROM catalog.sucursales ORDER BY clave LIMIT 1").fetchone()["id"]


def _nomina(conn, sucursal, *, anio=2099, semana=1, monto="100.00"):
    conn.execute(
        "INSERT INTO finance.nomina_semanal (sucursal_id, anio_iso, semana_iso, monto, registrada_por) VALUES (%s, %s, %s, %s, 'pytest-bd')",
        (sucursal, anio, semana, monto),
    )


def test_nomina_acepta_un_registro_valido_y_rechaza_un_duplicado_de_la_misma_semana():
    with _transaccion() as conn:
        sucursal = _sucursal(conn)
        _nomina(conn, sucursal)
        with pytest.raises(errors.UniqueViolation):
            _nomina(conn, sucursal)


@pytest.mark.parametrize("campos", [{"monto": "-1.00"}, {"semana": 54}, {"semana": 0}, {"anio": 1999}])
def test_nomina_rechaza_montos_negativos_y_semanas_o_anios_fuera_de_rango(campos):
    with _transaccion() as conn:
        with pytest.raises(errors.CheckViolation):
            _nomina(conn, _sucursal(conn), **campos)


@pytest.mark.parametrize("mes, importe", [(13, "10.00"), (0, "10.00"), (6, "-5.00")])
def test_cierre_de_comisiones_rechaza_mes_o_importe_invalidos(mes, importe):
    with _transaccion() as conn:
        with pytest.raises(errors.CheckViolation):
            conn.execute(
                """INSERT INTO finance.comision_cierres (sucursal_id, concepto, anio, mes, importe_real, actualizado_por)
                   VALUES (%s, 'VISA', 2099, %s, %s, 'pytest-bd')""",
                (_sucursal(conn), mes, importe),
            )


def test_el_cierre_de_provision_exige_periodo_ordenado():
    with _transaccion() as conn:
        definiciones = [
            fila["d"] for fila in conn.execute(
                """SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint
                   WHERE conrelid = 'finance.cierres_provision_fija'::regclass AND contype = 'c'"""
            ).fetchall()
        ]
        assert any("periodo_desde <= periodo_hasta" in d for d in definiciones)


def test_el_rfc_de_proveedor_es_unico_pero_se_admite_vacio_repetido():
    with _transaccion() as conn:
        conn.execute("INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado, rfc) VALUES ('Pytest BD uno', 'PYTEST BD UNO', 'XAXX010101000')")
        with pytest.raises(errors.UniqueViolation):
            conn.execute("INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado, rfc) VALUES ('Pytest BD dos', 'PYTEST BD DOS', 'XAXX010101000')")
    with _transaccion() as conn:
        conn.execute("INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado) VALUES ('Pytest BD tres', 'PYTEST BD TRES')")
        conn.execute("INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado) VALUES ('Pytest BD cuatro', 'PYTEST BD CUATRO')")


def test_un_proveedor_no_puede_tener_dos_gastos_fijos():
    with _transaccion() as conn:
        indice = conn.execute(
            """SELECT 1 FROM pg_indexes
               WHERE schemaname = 'catalog' AND tablename = 'gastos_fijos' AND indexdef LIKE '%UNIQUE%(proveedor_id)%'"""
        ).fetchone()
        assert indice, "Falta la unicidad de catalog.gastos_fijos.proveedor_id"
