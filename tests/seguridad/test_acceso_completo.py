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
