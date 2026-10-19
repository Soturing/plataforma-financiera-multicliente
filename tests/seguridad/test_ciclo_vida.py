"""Fase 6: ciclo de vida (ciclo-vida-usuarios §8–§15).

Las llamadas a Keycloak se sustituyen por un doble que registra lo pedido; la
prueba de punta a punta con el proveedor real está en test_acceso_completo.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.seguridad import keycloak_admin
from app.seguridad.mantenimiento import revisar_inactividad
from app.seguridad.sesiones import COOKIE

CATALOGOS = "/api/v1/catalogos"


class IdpFalso:
    def __init__(self) -> None:
        self.llamadas: list[tuple] = []
        self.credenciales: dict[str, list[dict]] = {}

    def registrar(self, nombre):
        def _f(*args, **kwargs):
            self.llamadas.append((nombre, args, kwargs))
            if nombre == "autenticadores":
                return self.credenciales.get(args[0], [])
            if nombre == "eliminar_todos_los_autenticadores":
                return len(self.credenciales.pop(args[0], []))
            if nombre == "eliminar_autenticador":
                self.credenciales[args[0]] = [c for c in self.credenciales.get(args[0], []) if c["id"] != args[1]]
            return None
        return _f

    def hechas(self, nombre):
        return [c for c in self.llamadas if c[0] == nombre]


@pytest.fixture
def idp(monkeypatch):
    falso = IdpFalso()
    for nombre in ("autenticadores", "eliminar_autenticador", "eliminar_todos_los_autenticadores", "habilitar",
                   "deshabilitar", "cerrar_sesiones", "enviar_invitacion", "fijar_llave_fisica"):
        monkeypatch.setattr(keycloak_admin, nombre, falso.registrar(nombre))
    return falso


@pytest.fixture
def cliente(base_control, tenant):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def modo_seguro():
    s = get_settings()
    anterior, s.acceso_modo = s.acceso_modo, "seguro"
    yield
    s.acceso_modo = anterior


def como(cliente: TestClient, token: str) -> TestClient:
    cliente.cookies.clear()
    cliente.cookies.set(COOKIE, token)
    return cliente


def codigo(r):
    d = r.json().get("detail")
    return d.get("codigo") if isinstance(d, dict) else None


def evento(control_app, tipo, recurso):
    return control_app.execute(
        "SELECT * FROM control.auditoria WHERE tipo = %s AND recurso_id = %s ORDER BY id DESC LIMIT 1", (tipo, str(recurso))
    ).fetchone()


def notificaciones(control_app, identidad_id):
    return [n["tipo"] for n in control_app.execute(
        "SELECT tipo FROM control.notificaciones WHERE identidad_id = %s ORDER BY id", (identidad_id,)
    ).fetchall()]


# --------------------------------------------------------------------------- #
# Asignaciones (§8)


def test_director_agrega_rol_con_alcance_por_restaurante(cliente, fabrica, control_app, idp):
    director, _, token = fabrica.persona("CONSULTORA_DIRECTOR")
    otra = fabrica.identidad()
    r = como(cliente, token).post(f"/api/v1/seguridad/identidades/{otra['id']}/asignaciones", json={
        "rol": "CONSULTORA_CAPTURISTA", "restaurantes": ["REST-UNO"], "motivo": "Alta para cierre semanal"})
    assert r.status_code == 201, r.text
    alcance = control_app.execute(
        "SELECT sucursales FROM control.alcance_asignacion WHERE asignacion_id = %s", (r.json()["asignacion_id"],)
    ).fetchone()["sucursales"]
    assert alcance == ["CENTRO", "NORTE"]
    assert evento(control_app, "AMPLIACION_ACCESO", otra["id"])["motivo"] == "Alta para cierre semanal"
    assert "AMPLIACION_ACCESO" in notificaciones(control_app, otra["id"])


def test_nadie_modifica_su_propio_acceso(cliente, fabrica, idp):
    director, _, token = fabrica.persona("CONSULTORA_DIRECTOR")
    r = como(cliente, token).post(f"/api/v1/seguridad/identidades/{director['id']}/asignaciones", json={
        "rol": "CONSULTORA_CAPTURISTA", "motivo": "Intento propio"})
    assert r.status_code == 403


def test_seguridad_no_otorga_roles_globales(cliente, fabrica, idp):
    _, _, token = fabrica.persona("CONSULTORA_SEGURIDAD")
    otra = fabrica.identidad()
    r = como(cliente, token).post(f"/api/v1/seguridad/identidades/{otra['id']}/asignaciones", json={
        "rol": "CONSULTORA_DIRECTOR", "motivo": "Intento de escalada"})
    assert r.status_code == 403


def test_rol_global_exige_reautenticacion_inmediata(cliente, fabrica, idp):
    _, _, token = fabrica.persona("CONSULTORA_DIRECTOR", autenticado_hace=timedelta(minutes=10))
    otra = fabrica.identidad()
    r = como(cliente, token).post(f"/api/v1/seguridad/identidades/{otra['id']}/asignaciones", json={
        "rol": "CONSULTORA_SEGURIDAD", "motivo": "Segunda persona de seguridad"})
    assert r.status_code == 401 and codigo(r) == "REAUTENTICACION_REQUERIDA"


def test_reducir_alcance_cierra_las_sesiones_afectadas(cliente, fabrica, control_app, idp, modo_seguro):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona, asig, token = fabrica.persona("CONSULTORA_CAPTURISTA", restaurantes=["REST-UNO"])
    assert como(cliente, token).get(CATALOGOS).status_code == 200
    r = como(cliente, admin).put(f"/api/v1/seguridad/asignaciones/{asig['id']}", json={
        "sucursales": ["NORTE"], "motivo": "Sólo atiende la sucursal Norte"})
    assert r.status_code == 200 and r.json()["tipo"] == "REDUCCION"
    assert como(cliente, token).get(CATALOGOS).status_code == 401
    assert "REDUCCION_ACCESO" in notificaciones(control_app, persona["id"])


def test_agregar_exportacion_es_ampliacion(cliente, fabrica, control_app, idp):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona, asig, _ = fabrica.persona("CONSULTORA_CAPTURISTA", sucursales=["NORTE"])
    r = como(cliente, admin).put(f"/api/v1/seguridad/asignaciones/{asig['id']}", json={
        "sucursales": ["NORTE"], "condicionados": ["EXPORTAR_CSV"], "motivo": "Exporta el cierre mensual"})
    assert r.json()["tipo"] == "AMPLIACION"
    assert evento(control_app, "AMPLIACION_ACCESO", persona["id"])


def test_revocar_rol_cierra_sus_sesiones(cliente, fabrica, idp, modo_seguro):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    _, asig, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    r = como(cliente, admin).post(f"/api/v1/seguridad/asignaciones/{asig['id']}/revocar", json={"motivo": "Cambio de puesto"})
    assert r.status_code == 200 and r.json()["sesiones_revocadas"] == 1
    assert como(cliente, token).get(CATALOGOS).status_code == 401


# --------------------------------------------------------------------------- #
# Baja, reingreso y reactivación (§11, §14, §15)


def test_baja_revoca_todo_y_se_verifica(cliente, fabrica, control_app, idp, modo_seguro):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    idp.credenciales[persona["idp_subject"]] = [{"id": "c1", "tipo": "webauthn-passwordless"}]
    r = como(cliente, admin).post(f"/api/v1/seguridad/identidades/{persona['id']}/baja", json={"motivo": "Fin de la relación laboral"})
    assert r.status_code == 200, r.text
    pasos = r.json()
    assert pasos["verificacion"] == "ok" and pasos["segundos"] < 900
    assert pasos["asignaciones_revocadas"] == 1 and pasos["autenticadores_revocados"] == 1
    assert idp.hechas("deshabilitar")
    assert como(cliente, token).get(CATALOGOS).status_code == 401
    fila = control_app.execute("SELECT estado FROM control.identidades WHERE id = %s", (persona["id"],)).fetchone()
    assert fila["estado"] == "BAJA_DEFINITIVA"   # la identidad no se elimina: conserva la trazabilidad


def test_reingreso_no_restaura_permisos(cliente, fabrica, control_app, idp):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona, _, _ = fabrica.persona("CONSULTORA_CAPTURISTA")
    como(cliente, admin).post(f"/api/v1/seguridad/identidades/{persona['id']}/baja", json={"motivo": "Salida temporal"})
    r = como(cliente, admin).post(f"/api/v1/seguridad/identidades/{persona['id']}/reingreso", json={"motivo": "Regresa al equipo"})
    assert r.status_code == 200 and r.json()["estado"] == "INVITADA"
    activas = control_app.execute(
        "SELECT count(*) AS n FROM control.asignaciones WHERE identidad_id = %s AND estado = 'ACTIVA'", (persona["id"],)
    ).fetchone()["n"]
    assert activas == 0
    assert idp.hechas("enviar_invitacion")


def test_reactivar_cuenta_suspendida(cliente, fabrica, control_app, idp):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona = fabrica.identidad(estado="SUSPENDIDA")
    r = como(cliente, admin).post(f"/api/v1/seguridad/identidades/{persona['id']}/reactivar", json={"motivo": "Regresó de vacaciones"})
    assert r.status_code == 200
    assert idp.hechas("habilitar")
    assert "REACTIVACION" in notificaciones(control_app, persona["id"])


# --------------------------------------------------------------------------- #
# Autenticadores (§9)


def test_no_se_da_de_baja_el_ultimo_autenticador_propio(cliente, fabrica, idp):
    persona, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    idp.credenciales[persona["idp_subject"]] = [{"id": "unica", "tipo": "webauthn-passwordless", "tipo_nombre": "Passkey", "etiqueta": "Teléfono"}]
    r = como(cliente, token).post("/api/v1/seguridad/mi-cuenta/autenticadores/unica/perdido", json={"motivo": "Perdí el teléfono"})
    assert r.status_code == 409


def test_autenticador_perdido_cierra_sesiones_y_avisa(cliente, fabrica, control_app, idp, modo_seguro):
    persona, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    idp.credenciales[persona["idp_subject"]] = [
        {"id": "tel", "tipo": "webauthn-passwordless", "tipo_nombre": "Passkey", "etiqueta": "Teléfono"},
        {"id": "lap", "tipo": "webauthn-passwordless", "tipo_nombre": "Passkey", "etiqueta": "Laptop"},
    ]
    r = como(cliente, token).post("/api/v1/seguridad/mi-cuenta/autenticadores/tel/perdido", json={"motivo": "Perdí el teléfono"})
    assert r.status_code == 200 and r.json()["autenticadores_fuertes_restantes"] == 1
    assert como(cliente, token).get(CATALOGOS).status_code == 401
    assert "AUTENTICADOR_PERDIDO" in notificaciones(control_app, persona["id"])


def test_tras_codigo_de_recuperacion_no_opera_hasta_registrar_passkey(cliente, fabrica, control_app):
    persona, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    control_app.execute("UPDATE control.identidades SET requiere_nuevo_autenticador = true WHERE id = %s", (persona["id"],))
    control_app.commit()
    r = como(cliente, token).get(CATALOGOS)
    assert r.status_code == 403 and codigo(r) == "AUTENTICADOR_PENDIENTE"


# --------------------------------------------------------------------------- #
# Recuperación asistida (§10)


def test_recuperacion_asistida_espera_24_horas(cliente, fabrica, control_app, idp):
    _, _, admin = fabrica.persona("CONSULTORA_DIRECTOR")
    persona, _, _ = fabrica.persona("CONSULTORA_CAPTURISTA")
    r = como(cliente, admin).post(f"/api/v1/seguridad/identidades/{persona['id']}/recuperacion", json={
        "motivo": "Perdió todos sus dispositivos", "verificacion": "Videollamada con su responsable"})
    assert r.status_code == 201, r.text
    rec = r.json()["recuperacion_id"]
    temprano = como(cliente, admin).post(f"/api/v1/seguridad/recuperaciones/{rec}/ejecutar")
    assert temprano.status_code == 409
    # Pasan 24 horas.
    control_app.execute(
        "UPDATE control.recuperaciones SET solicitada_en = now() - interval '25 hours', "
        "ejecutable_desde = now() - interval '1 hour' WHERE id = %s", (rec,))
    control_app.commit()
    idp.credenciales[persona["idp_subject"]] = [{"id": "x", "tipo": "webauthn-passwordless"}]
    listo = como(cliente, admin).post(f"/api/v1/seguridad/recuperaciones/{rec}/ejecutar")
    assert listo.status_code == 200 and listo.json()["autenticadores_revocados"] == 1
    estado = control_app.execute("SELECT estado FROM control.identidades WHERE id = %s", (persona["id"],)).fetchone()["estado"]
    assert estado == "REGISTRO_PENDIENTE"
    assert {"RECUPERACION_SOLICITADA", "RECUPERACION_EJECUTADA"} <= set(notificaciones(control_app, persona["id"]))


def test_cuenta_privilegiada_solo_la_recupera_otro_director(cliente, fabrica, idp):
    _, _, seguridad = fabrica.persona("CONSULTORA_SEGURIDAD")
    director, _, _ = fabrica.persona("CONSULTORA_DIRECTOR")
    r = como(cliente, seguridad).post(f"/api/v1/seguridad/identidades/{director['id']}/recuperacion", json={
        "motivo": "Perdió sus llaves", "verificacion": "Presencial"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Inactividad (§12)


def test_inactividad_avisa_y_suspende(fabrica, control_app):
    ahora = datetime.now(timezone.utc)
    avisar = fabrica.identidad()
    fabrica.asignacion(avisar["id"], "CONSULTORA_CAPTURISTA")
    suspender = fabrica.identidad()
    fabrica.asignacion(suspender["id"], "CONSULTORA_CAPTURISTA")
    director = fabrica.identidad()
    fabrica.asignacion(director["id"], "CONSULTORA_DIRECTOR", tenant=False)
    for ident, dias in ((avisar, 85), (suspender, 91), (director, 31)):
        control_app.execute(
            "UPDATE control.identidades SET ultimo_acceso_en = %s, creado_en = %s WHERE id = %s",
            (ahora - timedelta(days=dias), ahora - timedelta(days=200), ident["id"]),
        )
    control_app.commit()
    resultado = revisar_inactividad(control_app, ahora, deshabilitar_idp=False)
    control_app.commit()
    assert avisar["correo"] in resultado["avisadas"]
    assert {suspender["correo"], director["correo"]} <= set(resultado["suspendidas"])
    # El aviso no se repite en el mismo ciclo.
    assert avisar["correo"] not in revisar_inactividad(control_app, ahora, deshabilitar_idp=False)["avisadas"]
