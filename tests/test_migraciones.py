import os

import psycopg
import pytest

from app import migraciones

URL = os.environ.get("TENANT_OWNER_URL")
TABLA = "public.zz_prueba_migraciones"

pytestmark = pytest.mark.skipif(not URL, reason="Falta TENANT_OWNER_URL (cuenta propietaria de la base desechable)")


@pytest.fixture
def carpeta(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE public.zz_prueba_a (id int);", encoding="utf-8")
    (tmp_path / "002_b.sql").write_text("CREATE TABLE public.zz_prueba_b (id int);", encoding="utf-8")
    (tmp_path / "semillas").mkdir()
    (tmp_path / "semillas" / "semilla.sql").write_text("INSERT INTO public.zz_prueba_a VALUES (1);", encoding="utf-8")
    yield tmp_path
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS public.zz_prueba_a, public.zz_prueba_b, public.zz_prueba_c")
        c.execute(f"DROP TABLE IF EXISTS {TABLA}")


def _existe(tabla: str) -> bool:
    with psycopg.connect(URL) as c:
        return c.execute("SELECT to_regclass(%s)", (tabla,)).fetchone()[0] is not None


def test_aplica_en_orden_y_es_idempotente(carpeta):
    assert migraciones.aplicar(URL, carpeta=carpeta, tabla=TABLA) == ["001_a.sql", "002_b.sql"]
    assert migraciones.aplicar(URL, carpeta=carpeta, tabla=TABLA) == []
    assert _existe("public.zz_prueba_a") and _existe("public.zz_prueba_b")


def test_la_semilla_corre_justo_despues_de_su_migracion(carpeta):
    (carpeta / "003_c.sql").write_text(
        "CREATE TABLE public.zz_prueba_c AS SELECT count(*) AS filas FROM public.zz_prueba_a;", encoding="utf-8"
    )
    hechas = migraciones.aplicar(
        URL, carpeta=carpeta, tabla=TABLA, semillas=[("001", carpeta / "semillas" / "semilla.sql")]
    )
    assert hechas == ["001_a.sql", "semilla:semilla.sql", "002_b.sql", "003_c.sql"]
    with psycopg.connect(URL) as c:
        # 003 vio la fila sembrada: la semilla entró antes que las migraciones siguientes.
        assert c.execute("SELECT filas FROM public.zz_prueba_c").fetchone()[0] == 1


def test_una_migracion_que_falla_no_queda_registrada(carpeta):
    (carpeta / "002_b.sql").write_text("CREATE TABLE public.zz_prueba_b (id int); SELECT 1/0;", encoding="utf-8")
    with pytest.raises(psycopg.errors.DivisionByZero):
        migraciones.aplicar(URL, carpeta=carpeta, tabla=TABLA)
    assert not _existe("public.zz_prueba_b")  # la transacción se deshizo
    with psycopg.connect(URL) as c:
        assert [f[0] for f in c.execute(f"SELECT nombre FROM {TABLA}").fetchall()] == ["001_a.sql"]


def test_hasta_previas_adopta_una_base_ya_migrada_sin_ejecutar(carpeta):
    hechas = migraciones.aplicar(URL, carpeta=carpeta, tabla=TABLA, hasta_previas="001")
    assert hechas == ["002_b.sql"]
    assert not _existe("public.zz_prueba_a")  # 001 se marcó, no se ejecutó
