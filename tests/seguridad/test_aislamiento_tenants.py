"""Fase 5: aislamiento entre clientes (stacks separados) y entre sucursales (RLS).

Requiere dos data planes dados de alta con `python -m app.plataforma.tenants alta`:
GRUPO-DEMO y GRUPO-PRUEBA-B. Sin ellos, las pruebas se omiten.
"""
from __future__ import annotations

from datetime import date

import psycopg
import pytest

from app.plataforma import tenants

A, B = "GRUPO-DEMO", "GRUPO-PRUEBA-B"


def _entorno(clave: str) -> dict[str, str]:
    if not tenants.leer_entorno(tenants.ruta_entorno(clave)):
        pytest.skip(f"Data plane {clave} no dado de alta")
    try:
        env = tenants.entorno(clave)  # contraseñas desde OpenBao (D-025)
    except Exception as error:
        pytest.skip(f"Secretos de {clave} no disponibles: {error}")
    try:
        with tenants.conectar(env["FACTURAS_DATABASE_URL"], tenant=clave) as c:
            c.execute("SELECT 1")
    except psycopg.OperationalError:
        pytest.skip(f"Base de {clave} no disponible")
    return env


@pytest.fixture(scope="module")
def env_a():
    return _entorno(A)


@pytest.fixture(scope="module")
def env_b():
    return _entorno(B)


def _con(env, tenant, sucursales="*", usuario="tenant_runtime"):
    url = env["FACTURAS_DATABASE_URL"] if usuario == "tenant_runtime" else tenants.url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD")
    return tenants.conectar(url, tenant=tenant, sucursales=sucursales)


# --------------------------------------------------------------------------- #
# Entre clientes


@pytest.mark.parametrize("clave", [A, B])
def test_verificacion_de_aislamiento_de_cada_cliente(clave):
    env = _entorno(clave)
    assert tenants.verificar(clave, env) == []


def test_credenciales_de_un_cliente_no_abren_la_base_del_otro(env_a, env_b):
    url_a_en_b = env_a["FACTURAS_DATABASE_URL"].replace(f":{env_a['DP_DB_PORT']}/", f":{env_b['DP_DB_PORT']}/")
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(url_a_en_b, connect_timeout=5)


def test_bases_distintas_con_identidad_propia(env_a, env_b):
    with _con(env_a, A) as ca, _con(env_b, B) as cb:
        assert ca.execute("SELECT tenant_clave FROM seguridad.identidad_tenant").fetchone()["tenant_clave"] == A
        assert cb.execute("SELECT tenant_clave FROM seguridad.identidad_tenant").fetchone()["tenant_clave"] == B
        ids_a = {r["id"] for r in ca.execute("SELECT id FROM catalog.sucursales").fetchall()}
        ids_b = {r["id"] for r in cb.execute("SELECT id FROM catalog.sucursales").fetchall()}
        assert ids_a and ids_b and not ids_a & ids_b


def test_backend_configurado_con_el_tenant_equivocado_no_ve_nada(env_a):
    """Si a la base de A se conecta un proceso que declara ser B, no obtiene ni escribe filas."""
    with _con(env_a, B) as c:
        assert c.execute("SELECT count(*) AS n FROM core.facturas").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM analytics.movimientos_gasto").fetchone()["n"] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            c.execute("INSERT INTO catalog.restaurantes (clave, nombre) VALUES ('INTRUSO', 'x')")


def test_vistas_de_analytics_respetan_rls(env_a):
    """Las vistas pertenecen a tenant_owner y también quedan filtradas (FORCE RLS)."""
    with _con(env_a, A, sucursales="") as c:
        assert c.execute("SELECT count(*) AS n FROM analytics.movimientos_gasto").fetchone()["n"] == 0


# --------------------------------------------------------------------------- #
# Entre sucursales del mismo cliente


def _sucursal(c, clave):
    return c.execute("SELECT id FROM catalog.sucursales WHERE clave = %s", (clave,)).fetchone()["id"]


def test_alcance_de_sucursal_filtra_facturas_y_sus_dependientes(env_a):
    with _con(env_a, A) as todo:
        demo_a = _sucursal(todo, "DEMO-A")
        total = todo.execute("SELECT count(*) AS n FROM core.facturas").fetchone()["n"]
        de_a = todo.execute("SELECT count(*) AS n FROM core.facturas WHERE sucursal_id = %s", (demo_a,)).fetchone()["n"]
        ocr_de_a = todo.execute(
            "SELECT count(*) AS n FROM ocr.resultados r JOIN core.facturas f ON f.id = r.factura_id WHERE f.sucursal_id = %s",
            (demo_a,),
        ).fetchone()["n"]
    with _con(env_a, A, sucursales=str(demo_a)) as solo_a:
        assert solo_a.execute("SELECT count(*) AS n FROM core.facturas").fetchone()["n"] == de_a
        assert solo_a.execute(
            "SELECT count(*) AS n FROM core.facturas WHERE sucursal_id <> %s", (demo_a,)
        ).fetchone()["n"] == 0
        assert solo_a.execute("SELECT count(*) AS n FROM ocr.resultados").fetchone()["n"] == ocr_de_a
        visibles = {r["clave"] for r in solo_a.execute("SELECT clave FROM catalog.sucursales").fetchall()}
        assert visibles == {"DEMO-A"}
    assert total >= de_a


def test_no_se_escribe_en_una_sucursal_fuera_del_alcance(env_a):
    with _con(env_a, A) as todo:
        demo_a, demo_b = _sucursal(todo, "DEMO-A"), _sucursal(todo, "DEMO-B")
    venta = ("INSERT INTO finance.ventas (sucursal_id, fecha, monto_neto, referencia, registrada_por) "
             "VALUES (%s, %s, 1, 'prueba-rls', 'prueba')")
    with _con(env_a, A) as todo:
        todo.execute(venta, (demo_b, date(2001, 1, 1)))  # con alcance total, la misma fila sí entra
        todo.rollback()
    with _con(env_a, A, sucursales=str(demo_a)) as solo_a:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            solo_a.execute(venta, (demo_b, date(2001, 1, 1)))
        solo_a.rollback()


def test_sin_alcance_declarado_no_hay_filas(env_a):
    with tenants.conectar(env_a["FACTURAS_DATABASE_URL"]) as c:
        assert c.execute("SELECT count(*) AS n FROM core.facturas").fetchone()["n"] == 0


def test_la_auditoria_del_negocio_es_de_solo_anexado_para_la_app(env_a):
    with _con(env_a, A) as c:
        with pytest.raises(psycopg.Error):
            c.execute("DELETE FROM audit.correcciones")
        c.rollback()
        with pytest.raises(psycopg.Error):
            c.execute("UPDATE audit.aprendizajes SET factura_id = NULL")


# --------------------------------------------------------------------------- #
# A través de la app (sólo con `python -m app.plataforma.tenants pruebas --clave GRUPO-DEMO`)


def test_consolidado_por_la_app_solo_trae_las_sucursales_asignadas(env_a, base_control, tenant, fabrica):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.database import rls_verificado
    from app.main import app
    from app.seguridad.sesiones import COOKIE

    if get_settings().tenant_clave != A or not rls_verificado():
        pytest.skip("La app de prueba no apunta al data plane de GRUPO-DEMO con RLS")
    with _con(env_a, A) as todo:
        demo_a = _sucursal(todo, "DEMO-A")
        esperadas = todo.execute("SELECT count(*) AS n FROM core.facturas WHERE sucursal_id = %s", (demo_a,)).fetchone()["n"]
        ajena = todo.execute("SELECT id FROM core.facturas WHERE sucursal_id <> %s LIMIT 1", (demo_a,)).fetchone()
    with fabrica._conn() as conn:
        conn.execute(
            "INSERT INTO control.sucursales (tenant_id, clave, nombre, data_plane_id) VALUES (%s, 'DEMO-A', 'Demo A', %s) "
            "ON CONFLICT (tenant_id, clave) DO UPDATE SET data_plane_id = EXCLUDED.data_plane_id",
            (tenant["id"], demo_a),
        )
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA", sucursales=["DEMO-A"])
    with TestClient(app) as cliente:
        cliente.cookies.set(COOKIE, token)
        resumen = cliente.get("/api/v1/revision/resumen")
        assert resumen.status_code == 200, resumen.text   # el consolidado ya no se bloquea: lo filtra la base
        assert resumen.json()["total"] <= esperadas
        if ajena:
            assert cliente.get(f"/api/v1/facturas/{ajena['id']}").status_code == 404
