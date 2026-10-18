"""Fases 3 y 4: sesiones, contexto y autorización en el servidor para cada ruta."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.seguridad.autorizacion import actor_actual, autorizar_ruta
from app.seguridad.sesiones import COOKIE

CATALOGOS = "/api/v1/catalogos"
IDENTIDADES = "/api/v1/seguridad/identidades"
RESULTADOS = "/api/v1/finanzas/estado-resultados"
CSV = "/api/v1/analytics/exportar.csv"


@pytest.fixture
def cliente(base_control, tenant):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def modo_seguro():
    s = get_settings()
    anterior = s.acceso_modo
    s.acceso_modo = "seguro"
    yield
    s.acceso_modo = anterior


def con(cliente: TestClient, token: str | None) -> TestClient:
    cliente.cookies.clear()
    if token:
        cliente.cookies.set(COOKIE, token)
    return cliente


def codigo(respuesta) -> str | None:
    detalle = respuesta.json().get("detail")
    return detalle.get("codigo") if isinstance(detalle, dict) else None


def eventos(control_app, tipo: str) -> list[dict]:
    return control_app.execute("SELECT * FROM control.auditoria WHERE tipo = %s ORDER BY id", (tipo,)).fetchall()


# --------------------------------------------------------------------------- #
# Modo abierto y modo seguro


def test_modo_abierto_conserva_el_uso_anonimo_de_los_datos(cliente):
    assert con(cliente, None).get(CATALOGOS).status_code == 200


def test_administracion_exige_sesion_incluso_en_modo_abierto(cliente):
    r = con(cliente, None).get(IDENTIDADES)
    assert r.status_code == 401 and codigo(r) == "SESION_REQUERIDA"


def test_modo_seguro_exige_sesion_en_todo(cliente, modo_seguro):
    r = con(cliente, None).get(CATALOGOS)
    assert r.status_code == 401 and codigo(r) == "SESION_REQUERIDA"
    assert con(cliente, None).get("/health").status_code == 200


def test_sesion_desconocida_en_modo_seguro(cliente, modo_seguro):
    assert con(cliente, "token-inventado").get(CATALOGOS).status_code == 401


# --------------------------------------------------------------------------- #
# Roles y módulos


def test_administrador_de_seguridad_no_accede_a_finanzas(cliente, fabrica, control_app):
    ident, _, token = fabrica.persona("CONSULTORA_SEGURIDAD")
    r = con(cliente, token).get(RESULTADOS)
    assert r.status_code == 403 and codigo(r) == "SIN_PERMISO"
    denegados = [e for e in eventos(control_app, "ACCESO_DENEGADO") if e["actor_id"] == ident["id"]]
    assert denegados and denegados[-1]["modulo"] == "FINANZAS"
    assert con(cliente, token).get(IDENTIDADES).status_code == 200


def test_director_consulta_finanzas_y_queda_auditado(cliente, fabrica, control_app):
    ident, _, token = fabrica.persona("CONSULTORA_DIRECTOR")
    r = con(cliente, token).get(IDENTIDADES)
    assert r.status_code == 200
    autorizados = [e for e in eventos(control_app, "OPERACION_AUTORIZADA") if e["actor_id"] == ident["id"]]
    assert autorizados and autorizados[-1]["tenant_id"] is not None


def test_capturista_sin_permiso_individual_no_descarga_csv(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    r = con(cliente, token).get(CSV, params={"sucursal_clave": "NORTE"})
    assert r.status_code == 403 and codigo(r) == "SIN_PERMISO"


def test_csv_con_permiso_exige_reautenticacion_inmediata(cliente, fabrica):
    _, _, token = fabrica.persona(
        "CONSULTORA_CAPTURISTA", condicionados=["EXPORTAR_CSV"], autenticado_hace=timedelta(minutes=20)
    )
    r = con(cliente, token).get(CSV, params={"sucursal_clave": "NORTE"})
    assert r.status_code == 401 and codigo(r) == "REAUTENTICACION_REQUERIDA"


def test_modulos_no_asignados_se_deniegan(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA", modulos=["DOCUMENTOS"])
    assert con(cliente, token).get(RESULTADOS).status_code == 403


# --------------------------------------------------------------------------- #
# Sucursales


def test_sucursal_fuera_de_la_asignacion(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA", sucursales=["NORTE"])
    r = con(cliente, token).get(RESULTADOS, params={"sucursal_clave": "SUR"})
    assert r.status_code == 403 and codigo(r) == "SUCURSAL_FUERA_DE_ALCANCE"


def test_consolidado_se_deniega_con_sucursales_limitadas(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA", sucursales=["NORTE"])
    r = con(cliente, token).get(RESULTADOS)
    assert r.status_code == 403 and codigo(r) == "CONSOLIDADO_NO_PERMITIDO"


def test_sucursal_propia_pasa_la_autorizacion(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA", sucursales=["NORTE"])
    r = con(cliente, token).get(RESULTADOS, params={"sucursal_clave": "NORTE"})
    assert r.status_code not in (401, 403)


# --------------------------------------------------------------------------- #
# Ciclo de la sesión


def test_retirar_la_asignacion_invalida_la_sesion_en_la_siguiente_peticion(cliente, fabrica, control_app, modo_seguro):
    _, asig, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    assert con(cliente, token).get(CATALOGOS).status_code == 200
    control_app.execute("UPDATE control.asignaciones SET estado = 'REVOCADA' WHERE id = %s", (asig["id"],))
    control_app.commit()
    assert con(cliente, token).get(CATALOGOS).status_code == 401
    # Reutilizar la sesión revocada genera una alerta.
    assert con(cliente, token).get(CATALOGOS).status_code == 401
    assert eventos(control_app, "SESION_REVOCADA_REUTILIZADA")


def test_identidad_suspendida_pierde_la_sesion(cliente, fabrica, control_app, modo_seguro):
    ident, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    control_app.execute("UPDATE control.identidades SET estado = 'SUSPENDIDA' WHERE id = %s", (ident["id"],))
    control_app.commit()
    assert con(cliente, token).get(CATALOGOS).status_code == 401


def test_inactividad_y_duracion_maxima(cliente, fabrica, modo_seguro):
    ident = fabrica.identidad()
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA")
    inactiva = fabrica.sesion(ident["id"], asig, inactividad=timedelta(seconds=-1))
    vencida = fabrica.sesion(ident["id"], asig, expira_en=timedelta(seconds=-1))
    assert con(cliente, inactiva).get(CATALOGOS).status_code == 401
    assert con(cliente, vencida).get(CATALOGOS).status_code == 401


def test_sin_contexto_hay_que_elegir_cliente_y_rol(cliente, fabrica):
    ident = fabrica.identidad()
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA")
    token = fabrica.sesion(ident["id"], None)
    r = con(cliente, token).get(CATALOGOS)
    assert r.status_code == 409 and codigo(r) == "CONTEXTO_REQUERIDO"
    elegido = con(cliente, token).post("/api/v1/seguridad/contexto", json={"asignacion_id": str(asig["id"])})
    assert elegido.status_code == 200 and elegido.json()["rol"] == "CONSULTORA_CAPTURISTA"
    assert con(cliente, token).get(CATALOGOS).status_code == 200


def test_rol_privilegiado_exige_llave_fisica(cliente, fabrica):
    ident = fabrica.identidad()
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_DIRECTOR", tenant=False)
    token = fabrica.sesion(ident["id"], None, llave_fisica=False)
    r = con(cliente, token).post("/api/v1/seguridad/contexto", json={"asignacion_id": str(asig["id"])})
    assert r.status_code == 403


def test_cambiar_de_rol_exige_reautenticacion(cliente, fabrica):
    """D-020: una persona con dos roles opera con uno a la vez y cambia sólo tras reautenticarse."""
    ident = fabrica.identidad()
    director = fabrica.asignacion(ident["id"], "CONSULTORA_DIRECTOR", tenant=False)
    seguridad = fabrica.asignacion(ident["id"], "CONSULTORA_SEGURIDAD", tenant=False)
    token = fabrica.sesion(ident["id"], director, llave_fisica=True, autenticado_hace=timedelta(minutes=10))
    r = con(cliente, token).post("/api/v1/seguridad/contexto", json={"asignacion_id": str(seguridad["id"])})
    assert r.status_code == 401 and "/auth/reautenticar" in r.json()["detail"]["url"]
    reciente = fabrica.sesion(ident["id"], director, llave_fisica=True, autenticado_hace=timedelta(minutes=1))
    assert con(cliente, reciente).post("/api/v1/seguridad/contexto", json={"asignacion_id": str(seguridad["id"])}).status_code == 200


def test_sesion_publica_no_expone_el_token(cliente, fabrica):
    _, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    datos = con(cliente, token).get("/api/v1/seguridad/sesion").json()
    assert datos["autenticado"] is True and token not in str(datos)
    assert "DOCUMENTOS" in datos["modulos"]


# --------------------------------------------------------------------------- #
# Autor de la operación (D-014)


def test_el_autor_sale_de_la_sesion_y_no_del_navegador(base_control, tenant, fabrica):
    prueba = FastAPI(dependencies=[Depends(autorizar_ruta)])

    @prueba.post("/api/v1/facturas/{factura_id}/rechazar")
    def eco(factura_id: str, cuerpo: dict):
        return {"cuerpo": cuerpo, "actor": actor_actual.get()}

    ident, _, token = fabrica.persona("CONSULTORA_CAPTURISTA")
    with TestClient(prueba) as c:
        c.cookies.set(COOKIE, token)
        r = c.post("/api/v1/facturas/1/rechazar", json={"revisada_por": "alguien más", "motivo": "x"})
    assert r.status_code == 200, r.text
    assert r.json()["cuerpo"]["revisada_por"] == f"Persona de Prueba <{ident['correo']}>"
    assert r.json()["actor"] == f"Persona de Prueba <{ident['correo']}>"
