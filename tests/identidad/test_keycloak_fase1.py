"""Prueba técnica de la fase 1 (D-021): el proveedor de identidad cumple el diseño.

Requiere el entorno local: `docker compose --profile identidad up -d identidad correo-pruebas`.
Sin él, las pruebas se omiten.
"""
from __future__ import annotations

import secrets
import time

import httpx
import pytest

pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from autenticador_software import AAGUID_SOFTWARE, AutenticadorSoftware
from cliente_keycloak import (
    REALM,
    AdminKeycloak,
    CorreoPruebas,
    Navegador,
    Pagina,
    configuracion,
    decodificar_sin_verificar,
    disponible,
)

pytestmark = pytest.mark.skipif(not disponible(), reason="Keycloak local no disponible (perfil `identidad`)")

# AAGUID de una llave física cualquiera: basta con que no sea el del autenticador de software.
AAGUID_LLAVE_FISICA = "ee882879-721c-4913-9775-3dfcce97072a"


@pytest.fixture(scope="module")
def conf():
    return configuracion()


@pytest.fixture(scope="module")
def admin(conf):
    return AdminKeycloak(conf)


@pytest.fixture(scope="module")
def correo(conf):
    return CorreoPruebas(conf)


@pytest.fixture
def usuarios(admin):
    creados: list[str] = []

    def crear(*, rol_global: bool = False) -> tuple[str, str]:
        email = f"prueba-{secrets.token_hex(4)}@demo.test"
        user_id = admin.crear_usuario(email, rol_global=rol_global)
        creados.append(user_id)
        return email, user_id

    yield crear
    for user_id in creados:
        admin.borrar_usuario(user_id)


@pytest.fixture
def lista_aaguid(admin):
    """Permite cambiar la lista de llaves físicas aceptadas y la restaura al final.

    Keycloak ignora un PUT con sólo la lista: hay que enviar la política completa."""
    original = admin.realm()["webAuthnPolicyAcceptableAaguids"]

    def fijar(aaguids: list[str]) -> None:
        politica = {k: v for k, v in admin.realm().items() if k.startswith("webAuthnPolicy")}
        politica["webAuthnPolicyAcceptableAaguids"] = aaguids
        admin.actualizar_realm(politica)
        assert admin.realm()["webAuthnPolicyAcceptableAaguids"] == aaguids

    yield fijar
    fijar(original)


def invitar(admin, correo, conf, email, user_id, acciones, autenticador=None) -> Navegador:
    admin.enviar_acciones(user_id, acciones)
    nav = Navegador(conf, autenticador)
    nav.completar_invitacion(correo.enlace_para(email))
    return nav


def tipos(admin, user_id) -> set[str]:
    return {c["type"] for c in admin.credenciales(user_id)}


# --------------------------------------------------------------------------- #
# 1. Registro con passkey y acceso sin contraseña


def test_invitacion_registra_passkey_y_codigos(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless", "CONFIGURE_RECOVERY_AUTHN_CODES"])

    assert tipos(admin, user_id) == {"webauthn-passwordless", "recovery-authn-codes"}


def test_acceso_con_passkey_entrega_identidad_verificable(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless"])

    resultado = Navegador(conf, nav.autenticador).iniciar_sesion(email)

    assert resultado.code, resultado.pagina and resultado.pagina.resumen()
    assert resultado.id_token["sub"] == user_id
    assert resultado.id_token["email"] == email
    assert "auth_time" in resultado.id_token


def test_usuario_sin_credencial_no_entra_ni_se_enrola(usuarios, conf):
    """Conocer el correo no basta: sin invitación no hay acceso ni registro de autenticador."""
    email, _ = usuarios()

    resultado = Navegador(conf).iniciar_sesion(email)

    assert resultado.code is None
    campos = {c for f in resultado.pagina.formularios for c in f["campos"]}
    assert "attestationObject" not in campos


def test_no_existe_acceso_con_contrasena(conf, usuarios):
    email, _ = usuarios()
    for client_id in ("facturas-app", "admin-cli", "account"):
        r = httpx.post(
            f"{conf['IDENTIDAD_URL']}/realms/{REALM}/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": client_id, "username": email, "password": "cualquiera"},
        )
        assert r.status_code in (400, 401), (client_id, r.text)
        assert "access_token" not in r.text


# --------------------------------------------------------------------------- #
# 2. Llave física por rol


@pytest.mark.parametrize(
    ("lista", "formato"),
    [
        pytest.param([AAGUID_LLAVE_FISICA], "packed-x5c", id="aaguid-fuera-de-la-lista"),
        pytest.param([str(AAGUID_SOFTWARE)], "packed", id="autoatestacion"),
        pytest.param([str(AAGUID_SOFTWARE)], "none", id="sin-atestacion"),
        pytest.param([str(AAGUID_SOFTWARE)], "packed-x5c", id="cadena-de-ca-no-confiable"),
    ],
)
def test_rol_global_rechaza_lo_que_no_es_llave_fisica_confiable(admin, correo, conf, usuarios, lista_aaguid, lista, formato):
    """Con lista de AAGUID, sólo entra una llave cuya atestación encadena a una raíz del truststore."""
    lista_aaguid(lista)
    email, user_id = usuarios(rol_global=True)

    invitar(admin, correo, conf, email, user_id, ["webauthn-register"], AutenticadorSoftware(origin=conf["IDENTIDAD_URL"], formato_atestacion=formato))

    assert "webauthn" not in tipos(admin, user_id)


def test_flujo_rol_global_con_llave(admin, correo, conf, usuarios):
    """Recorrido completo del rol global. En desarrollo la lista de AAGUID está vacía, por eso
    el autenticador de software sirve aquí; con lista configurada lo rechaza (prueba anterior).
    El recorrido con una llave física real se verifica a mano (docs/seguridad/fase1-identidad.md)."""
    email, user_id = usuarios(rol_global=True)
    llave = AutenticadorSoftware(origin=conf["IDENTIDAD_URL"], formato_atestacion="packed")
    invitar(admin, correo, conf, email, user_id, ["webauthn-register"], llave)
    assert tipos(admin, user_id) == {"webauthn"}

    resultado = Navegador(conf, llave).iniciar_sesion(email)

    assert resultado.code, resultado.pagina and resultado.pagina.resumen()
    roles = decodificar_sin_verificar(resultado.tokens["access_token"]).get("realm_access", {}).get("roles", [])
    assert "requiere-llave-fisica" in roles


def test_rol_global_no_entra_con_passkey(admin, correo, conf, usuarios):
    """Una passkey del dispositivo nunca basta para un rol global."""
    email, user_id = usuarios(rol_global=True)
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless"])
    assert "webauthn-passwordless" in tipos(admin, user_id)

    resultado = Navegador(conf, nav.autenticador).iniciar_sesion(email)

    assert resultado.code is None


def test_rol_operativo_no_lleva_rol_global_en_el_token(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless"])

    resultado = Navegador(conf, nav.autenticador).iniciar_sesion(email)

    roles = decodificar_sin_verificar(resultado.tokens["access_token"]).get("realm_access", {}).get("roles", [])
    assert "requiere-llave-fisica" not in roles


# --------------------------------------------------------------------------- #
# 3. Reautenticación forzada


def test_reautenticacion_forzada_exige_nueva_ceremonia(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless"])
    navegador = Navegador(conf, nav.autenticador)
    primero = navegador.iniciar_sesion(email)
    firmas_antes = nav.autenticador.credenciales[0].sign_count

    # Con la cookie de Keycloak, un acceso normal no pide otra ceremonia.
    silencioso = navegador.iniciar_sesion(email)
    assert silencioso.code and nav.autenticador.credenciales[0].sign_count == firmas_antes

    # Con max_age=0 y prompt=login, sí: el servidor de la app verifica auth_time.
    reautenticado = navegador.iniciar_sesion(email, prompt="login", max_age="0")
    assert reautenticado.code
    assert nav.autenticador.credenciales[0].sign_count == firmas_antes + 1
    assert reautenticado.id_token["auth_time"] >= primero.id_token["auth_time"]


# --------------------------------------------------------------------------- #
# 4. Códigos de recuperación en cuentas sin contraseña


def test_codigo_de_recuperacion_sustituye_a_la_passkey_una_sola_vez(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless", "CONFIGURE_RECOVERY_AUTHN_CODES"])
    codigo = nav.codigos_recuperacion[0]

    primero = Navegador(conf, AutenticadorSoftware(origin=conf["IDENTIDAD_URL"])).iniciar_sesion(email, usar="codigo", codigo=codigo)
    assert primero.code, primero.pagina and primero.pagina.resumen()

    repetido = Navegador(conf, AutenticadorSoftware(origin=conf["IDENTIDAD_URL"])).iniciar_sesion(email, usar="codigo", codigo=codigo)
    assert repetido.code is None


# --------------------------------------------------------------------------- #
# 5. Protección contra intentos repetidos


def test_bloqueo_temporal_tras_cinco_fallos(admin, correo, conf, usuarios):
    email, user_id = usuarios()
    nav = invitar(admin, correo, conf, email, user_id, ["webauthn-register-passwordless", "CONFIGURE_RECOVERY_AUTHN_CODES"])

    def estado() -> dict:
        return admin._req("GET", f"/attack-detection/brute-force/users/{user_id}").json()

    for intento in range(1, 6):
        # Más de 1 s entre intentos: así se mide el umbral de 5 y no la detección de
        # intentos rápidos, que bloquea antes (dos fallos en menos de 1 s).
        time.sleep(1.2)
        fallo = Navegador(conf).iniciar_sesion(email, usar="codigo", codigo="XXXX-XXXX-XXXX")
        assert fallo.code is None
        if intento == 4:
            assert estado()["disabled"] is False

    assert estado()["disabled"] is True and estado()["numFailures"] == 5

    # Con el usuario bloqueado, ni la passkey legítima entra.
    resultado = Navegador(conf, nav.autenticador).iniciar_sesion(email)
    assert resultado.code is None
    admin._req("DELETE", f"/attack-detection/brute-force/users/{user_id}")
