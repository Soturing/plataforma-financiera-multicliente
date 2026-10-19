"""Recorrido completo con Keycloak: invitación, acceso, reautenticación y cierre (fases 1–3).

Usa el autenticador WebAuthn de software de tests/identidad y la cuenta de servicio
`facturas-control` de la app. Sin Keycloak local, se omite.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "identidad"))
from cliente_keycloak import CorreoPruebas, Navegador, configuracion, disponible  # noqa: E402

from app.main import app  # noqa: E402
from app.seguridad import keycloak_admin  # noqa: E402
from app.seguridad.sesiones import COOKIE  # noqa: E402

pytestmark = pytest.mark.skipif(not disponible(), reason="Keycloak local no disponible (perfil `identidad`)")


@pytest.fixture
def persona_enrolada(fabrica):
    """Cuenta en Keycloak creada por la app, con passkey registrada desde su invitación."""
    conf = configuracion()
    ident = fabrica.identidad(estado="INVITADA")
    correo = ident["correo"]
    user_id = keycloak_admin.crear_usuario(correo, "Persona de Prueba", llave_fisica=False)
    with fabrica._conn() as conn:
        conn.execute("UPDATE control.identidades SET idp_subject = %s WHERE id = %s", (user_id, ident["id"]))
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA", sucursales=["NORTE"])
    keycloak_admin.enviar_invitacion(user_id, llave_fisica=False)
    navegador = Navegador(conf)
    navegador.completar_invitacion(CorreoPruebas(conf).enlace_para(correo))
    yield {"identidad": ident, "correo": correo, "asignacion": asig, "navegador": navegador, "user_id": user_id}
    keycloak_admin._req("DELETE", f"/users/{user_id}")


def _ir_por_keycloak(cliente: TestClient, ruta: str, persona: dict) -> None:
    salida = cliente.get(ruta, follow_redirects=False)
    assert salida.status_code == 303, salida.text
    datos = persona["navegador"].autenticar_desde(salida.headers["location"], persona["correo"])
    regreso = cliente.get("/auth/callback", params=datos, follow_redirects=False)
    assert regreso.status_code == 303, regreso.text


def test_acceso_reautenticacion_y_cierre(base_control, tenant, persona_enrolada, control_app):
    with TestClient(app) as cliente:
        _ir_por_keycloak(cliente, "/auth/entrar?destino=/%23/finanzas", persona_enrolada)
        assert COOKIE in cliente.cookies

        sesion = cliente.get("/api/v1/seguridad/sesion").json()
        assert sesion["autenticado"] is True
        assert sesion["rol"] == "CONSULTORA_CAPTURISTA"          # única asignación: se elige sola
        assert sesion["sucursales"] == ["NORTE"]
        assert sesion["llave_fisica"] is False
        # La invitación se activó con el primer acceso.
        estado = control_app.execute("SELECT estado FROM control.identidades WHERE id = %s",
                                     (persona_enrolada["identidad"]["id"],)).fetchone()["estado"]
        assert estado == "ACTIVA"

        antes = sesion["autenticado_en"]
        _ir_por_keycloak(cliente, "/auth/reautenticar?destino=/%23/", persona_enrolada)
        assert cliente.get("/api/v1/seguridad/sesion").json()["autenticado_en"] >= antes

        salida = cliente.post("/auth/salir")
        assert salida.status_code == 200 and "logout" in salida.json()["redirect"]
        assert cliente.get("/api/v1/seguridad/sesion").json()["autenticado"] is False

    tipos = [e["tipo"] for e in control_app.execute(
        "SELECT tipo FROM control.auditoria WHERE actor_id = %s ORDER BY id", (persona_enrolada["identidad"]["id"],)
    ).fetchall()]
    assert ["ACTIVACION", "INICIO_SESION", "CAMBIO_CONTEXTO", "REAUTENTICACION", "CIERRE_SESION"] == [
        t for t in tipos if t in {"ACTIVACION", "INICIO_SESION", "CAMBIO_CONTEXTO", "REAUTENTICACION", "CIERRE_SESION"}
    ]


def test_state_de_un_solo_uso(base_control, tenant, persona_enrolada):
    with TestClient(app) as cliente:
        salida = cliente.get("/auth/entrar", follow_redirects=False)
        datos = persona_enrolada["navegador"].autenticar_desde(salida.headers["location"], persona_enrolada["correo"])
        assert cliente.get("/auth/callback", params=datos, follow_redirects=False).status_code == 303
        cliente.cookies.clear()
        repetido = cliente.get("/auth/callback", params=datos, follow_redirects=False)
        assert parse_qs(urlparse(repetido.headers["location"].replace("#/", "")).query)["acceso"] == ["cancelado"]
        assert COOKIE not in cliente.cookies


def test_destino_externo_no_se_sigue():
    """El destino tras iniciar sesión sólo puede ser una ruta interna (sin redirección abierta)."""
    from app.seguridad.api import _destino_seguro

    assert _destino_seguro("https://sitio-ajeno.example/") == "/#/"
    assert _destino_seguro("//sitio-ajeno.example") == "/#/"
    assert _destino_seguro("/\sitio-ajeno.example") == "/#/"
    assert _destino_seguro("/#/finanzas") == "/#/finanzas"


# --------------------------------------------------------------------------- #
# Fase 6 con Keycloak real


def test_codigo_de_recuperacion_obliga_a_registrar_passkey_nueva(base_control, tenant, persona_enrolada, control_app):
    from autenticador_software import AutenticadorSoftware

    sin_passkey = Navegador(configuracion(), AutenticadorSoftware(origin=configuracion()["IDENTIDAD_URL"]))
    codigo = persona_enrolada["navegador"].codigos_recuperacion[0]
    with TestClient(app) as cliente:
        salida = cliente.get("/auth/entrar", follow_redirects=False)
        datos = sin_passkey.autenticar_desde(salida.headers["location"], persona_enrolada["correo"], usar="codigo", codigo=codigo)
        regreso = cliente.get("/auth/callback", params=datos, follow_redirects=False)
        assert regreso.status_code == 303 and regreso.headers["location"].startswith("/auth/registrar-autenticador")

        sesion = cliente.get("/api/v1/seguridad/sesion").json()
        assert sesion["metodo_auth"] == "CODIGO_RECUPERACION" and sesion["requiere_nuevo_autenticador"] is True
        bloqueado = cliente.get("/api/v1/catalogos")
        assert bloqueado.status_code == 403 and bloqueado.json()["detail"]["codigo"] == "AUTENTICADOR_PENDIENTE"

        # Registro de la passkey nueva con la sesión del proveedor (kc_action).
        hacia_registro = cliente.get(regreso.headers["location"], follow_redirects=False)
        sin_passkey.completar_invitacion(hacia_registro.headers["location"], etiqueta="passkey nueva")
        q = {k: v[0] for k, v in parse_qs(urlparse(sin_passkey.ultimo_callback).query).items()}
        assert q.get("kc_action_status") == "success"
        assert cliente.get("/auth/callback", params=q, follow_redirects=False).status_code == 303

        assert cliente.get("/api/v1/seguridad/sesion").json()["requiere_nuevo_autenticador"] is False
        assert cliente.get("/api/v1/catalogos").status_code == 200

    tipos = [e["tipo"] for e in control_app.execute(
        "SELECT tipo FROM control.auditoria WHERE actor_id = %s ORDER BY id", (persona_enrolada["identidad"]["id"],)
    ).fetchall()]
    assert "USO_CODIGO_RECUPERACION" in tipos and "AUTENTICADOR_REGISTRADO" in tipos


def test_tras_la_baja_la_passkey_ya_no_entra(base_control, tenant, persona_enrolada, fabrica):
    _, _, director = fabrica.persona("CONSULTORA_DIRECTOR")
    with TestClient(app) as cliente:
        cliente.cookies.set(COOKIE, director)
        r = cliente.post(f"/api/v1/seguridad/identidades/{persona_enrolada['identidad']['id']}/baja",
                         json={"motivo": "Prueba de baja de punta a punta"})
        assert r.status_code == 200 and r.json()["verificacion"] == "ok", r.text
        assert r.json()["autenticadores_revocados"] >= 1
    intento = Navegador(configuracion(), persona_enrolada["navegador"].autenticador).iniciar_sesion(persona_enrolada["correo"])
    assert intento.code is None
