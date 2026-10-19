"""Fase 7: secretos y claves por cliente (OpenBao) y respaldos cifrados (D-025).

Requiere OpenBao abierto, el destino de respaldos y los dos clientes dados de alta.
Sin ellos, las pruebas se omiten.
"""
from __future__ import annotations

import pytest

from app.plataforma import respaldos, secretos, tenants
from app.plataforma.secretos import Bao, SecretosError

A, B = "GRUPO-DEMO", "GRUPO-PRUEBA-B"


def _entorno(clave):
    env = tenants.leer_entorno(tenants.ruta_entorno(clave))
    if not env.get("SECRETOS_APP_ROLE_ID"):
        pytest.skip(f"{clave} sin secretos en OpenBao")
    return env


@pytest.fixture(scope="module", autouse=True)
def openbao_abierto():
    try:
        estado = Bao().estado()
    except Exception:
        pytest.skip("OpenBao no disponible")
    if not estado["initialized"] or estado["sealed"]:
        pytest.skip("OpenBao sellado o sin inicializar")


@pytest.fixture(scope="module")
def env_a():
    return _entorno(A)


@pytest.fixture(scope="module")
def env_b():
    return _entorno(B)


def _app(env):
    return Bao().login_approle(env["SECRETOS_APP_ROLE_ID"], env["SECRETOS_APP_SECRET_ID"])


# --------------------------------------------------------------------------- #
# Secretos y claves


def test_el_archivo_privado_no_tiene_contrasenas(env_a, env_b):
    for env in (env_a, env_b):
        assert not any(k in env for k in tenants.NO_SE_GUARDA)
        assert not any("postgresql://" in v for v in env.values())


def test_la_app_lee_solo_su_conexion(env_a):
    app = _app(env_a)
    assert app.leer(f"tenants/{A}/app")["database_url"].startswith("postgresql://tenant_runtime:")
    with pytest.raises(SecretosError):
        app.leer(f"tenants/{A}/base")          # contraseñas de administración
    with pytest.raises(SecretosError):
        app.leer(f"tenants/{B}/app")           # otro cliente


def test_cada_cliente_usa_solo_su_clave(env_a, env_b):
    app_a, app_b = _app(env_a), _app(env_b)
    cifrado = app_a.cifrar(f"{A}-datos", b"dato del cliente A")
    assert app_a.descifrar(f"{A}-datos", cifrado) == b"dato del cliente A"
    with pytest.raises(SecretosError):
        app_b.descifrar(f"{A}-datos", cifrado)
    with pytest.raises(SecretosError):
        app_a.descifrar(f"{A}-respaldos", cifrado)  # la app no toca la clave de respaldos


def test_la_contrasena_del_repositorio_solo_existe_cifrada(env_a):
    guardado = secretos.plataforma().leer(f"tenants/{A}/respaldos")
    assert "password_repositorio" not in guardado
    assert guardado["password_repositorio_cifrada"].startswith("vault:v")


def test_rotar_conserva_lo_cifrado_antes(env_a):
    app = _app(env_a)
    antes = app.cifrar(f"{A}-datos", b"antes de rotar")
    version = secretos.plataforma().rotar(f"{A}-datos")
    despues = app.cifrar(f"{A}-datos", b"despues de rotar")
    assert despues.startswith(f"vault:v{version}:")
    assert app.descifrar(f"{A}-datos", antes) == b"antes de rotar"


def test_plataforma_no_lee_politicas_globales_ni_borra_claves():
    bao = secretos.plataforma()
    with pytest.raises(SecretosError):
        bao._req("GET", "sys/policies/acl")
    with pytest.raises(SecretosError):
        bao._req("DELETE", f"transit/keys/{A}-datos")


# --------------------------------------------------------------------------- #
# Respaldos


@pytest.fixture(scope="module")
def respaldo_a(env_a):
    try:
        return respaldos.respaldar(A)
    except respaldos.RespaldoError as error:
        pytest.skip(f"Destino de respaldos no disponible: {error}")


def test_respaldo_y_restauracion_coinciden(respaldo_a):
    resultado = respaldos.probar_restauracion(A)
    assert resultado["tablas"]["core.facturas"] > 0
    assert resultado["archivos_en_respaldo"] == resultado["archivos_en_disco"]


def test_el_cliente_no_puede_borrar_sus_respaldos(respaldo_a):
    cred = respaldos._credenciales(A)
    instantanea = respaldos.listar(A)[0]["id"]
    with pytest.raises(respaldos.RespaldoError):
        respaldos._restic(cred, "forget", instantanea, "--prune")
    assert any(s["id"] == instantanea for s in respaldos.listar(A))


def test_un_cliente_no_lee_el_repositorio_de_otro(respaldo_a, env_b):
    """Con sus credenciales válidas, B intenta abrir la ruta del repositorio de A."""
    cred_b = respaldos._credenciales(B)
    respaldos._asegurar_repositorio(cred_b)
    respaldos._restic(cred_b, "snapshots")  # sus credenciales sí abren su propio repositorio
    ruta_a = cred_b["repositorio"].replace(f"/{B.lower()}/", f"/{A.lower()}/")
    assert ruta_a != cred_b["repositorio"]
    with pytest.raises(respaldos.RespaldoError):
        respaldos._restic({**cred_b, "repositorio": ruta_a}, "snapshots")
