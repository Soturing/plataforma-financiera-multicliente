"""Migración 034: la auditoría no se borra en cascada ni se reescribe, ni siquiera como propietaria."""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import get_settings
from app.errors import DomainError
from app.repository import delete_pending_invoices

ACTOR = "pytest-auditoria-034"


def _propietaria(purga: bool = False) -> psycopg.Connection:
    url = os.environ.get("TENANT_OWNER_URL")
    if not url:
        pytest.skip("Requiere TENANT_OWNER_URL (python -m app.plataforma.tenants pruebas)")
    opciones = f"-c app.tenant={get_settings().tenant_clave} -c app.sucursales=*"
    if purga:
        opciones += " -c audit.purga=on"
    return psycopg.connect(url, options=opciones, row_factory=dict_row)


@pytest.fixture()
def factura_con_correccion():
    with _propietaria() as c:
        sucursal = c.execute("SELECT id FROM catalog.sucursales ORDER BY clave LIMIT 1").fetchone()["id"]
        factura = c.execute(
            """
            INSERT INTO core.facturas (sucursal_id, canal, estado, archivo_url, archivo_nombre, archivo_mime,
                                       archivo_sha256, creada_por)
            VALUES (%s, 'web', 'requiere_revision', 'x', 'x.pdf', 'application/pdf', %s, %s) RETURNING id
            """,
            (sucursal, uuid4().hex + uuid4().hex, ACTOR),
        ).fetchone()["id"]
        ocr = c.execute(
            """
            INSERT INTO ocr.resultados (factura_id, version, proveedor_ocr, modelo_ocr, texto_raw, json_raw)
            VALUES (%s, 1, 'pytest', 'pytest', '', '{}') RETURNING id
            """,
            (factura,),
        ).fetchone()["id"]
        interpretacion = c.execute(
            """
            INSERT INTO ai.interpretaciones (factura_id, ocr_resultado_id, version, modelo_ia, reglas_version, salida_json)
            VALUES (%s, %s, 1, 'pytest', 'pytest', '{}') RETURNING id
            """,
            (factura, ocr),
        ).fetchone()["id"]
        revision = c.execute(
            """
            INSERT INTO core.revisiones (factura_id, interpretacion_id, decision, revisada_por)
            VALUES (%s, %s, 'corregida_y_aprobada', %s) RETURNING id
            """,
            (factura, interpretacion, ACTOR),
        ).fetchone()["id"]
        c.execute(
            """
            INSERT INTO audit.correcciones (revision_id, factura_id, campo, valor_propuesto, valor_corregido, corregido_por)
            VALUES (%s, %s, 'total', '1', '2', %s)
            """,
            (revision, factura, ACTOR),
        )
    yield factura
    with _propietaria(purga=True) as c:
        c.execute("DELETE FROM audit.correcciones WHERE factura_id = %s", (factura,))
        c.execute("DELETE FROM core.facturas WHERE id = %s", (factura,))


def test_no_se_borra_una_factura_con_correcciones(factura_con_correccion):
    with _propietaria() as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("DELETE FROM core.facturas WHERE id = %s", (factura_con_correccion,))


def test_la_bandeja_avisa_en_lugar_de_fallar(factura_con_correccion):
    with _propietaria() as c:
        with pytest.raises(DomainError, match="correcciones"):
            delete_pending_invoices(c, [factura_con_correccion], ACTOR)


@pytest.mark.parametrize("sentencia", [
    "UPDATE audit.correcciones SET motivo = 'x' WHERE factura_id = %s",
    "DELETE FROM audit.correcciones WHERE factura_id = %s",
])
def test_la_propietaria_no_reescribe_la_auditoria(factura_con_correccion, sentencia):
    with _propietaria() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="sólo anexado"):
            c.execute(sentencia, (factura_con_correccion,))


def test_tampoco_se_vacia_la_auditoria():
    with _propietaria() as c:
        for tabla in ("audit.correcciones", "audit.cambios_catalogo", "audit.documentos_eliminados", "audit.aprendizajes"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(f"TRUNCATE {tabla}")
            c.rollback()
