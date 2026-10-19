"""Fase 2: esquema del plano de control, cuenta de la app y bitácora inmutable."""
from uuid import uuid4

import psycopg
import pytest

from app.seguridad import control


def test_la_cuenta_de_la_app_no_es_privilegiada(control_app):
    fila = control_app.execute(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert fila == {"rolsuper": False, "rolbypassrls": False, "rolcreaterole": False, "rolcreatedb": False}
    propias = control_app.execute(
        "SELECT count(*) AS n FROM pg_tables WHERE schemaname = 'control' AND tableowner = current_user"
    ).fetchone()["n"]
    assert propias == 0


def test_bitacora_encadenada_e_integra(control_app):
    a = control.registrar_evento(control_app, "PRUEBA", actor_tipo="SISTEMA", detalle={"n": 1})
    b = control.registrar_evento(control_app, "PRUEBA", actor_tipo="SISTEMA", detalle={"n": 2})
    filas = control_app.execute(
        "SELECT id, hash, hash_anterior FROM control.auditoria WHERE id IN (%s, %s) ORDER BY id", (a, b)
    ).fetchall()
    assert filas[1]["hash_anterior"] == filas[0]["hash"]
    assert control.verificar_auditoria(control_app)["integra"] is True


@pytest.mark.parametrize("sentencia", [
    "UPDATE control.auditoria SET tipo = 'ALTERADO'",
    "DELETE FROM control.auditoria",
    "TRUNCATE control.auditoria",
])
def test_la_app_no_puede_alterar_la_bitacora(control_app, sentencia):
    control.registrar_evento(control_app, "PRUEBA", actor_tipo="SISTEMA")
    control_app.commit()
    with pytest.raises(psycopg.Error):
        control_app.execute(sentencia)
    control_app.rollback()


def test_ni_el_propietario_altera_la_bitacora_sin_que_se_note(owner):
    control.registrar_evento(owner, "PRUEBA", actor_tipo="SISTEMA", detalle={"importe": 100})
    with pytest.raises(psycopg.Error):
        owner.execute("UPDATE control.auditoria SET detalle = '{}'")
    owner.rollback()
    # Aun desactivando el disparador, la verificación detecta la alteración.
    owner.execute("ALTER TABLE control.auditoria DISABLE TRIGGER auditoria_sin_cambios")
    owner.execute("UPDATE control.auditoria SET detalle = '{\"importe\": 1}' WHERE id = (SELECT min(id) FROM control.auditoria)")
    resultado = control.verificar_auditoria(owner)
    owner.rollback()
    assert resultado["integra"] is False


def test_no_se_registran_secretos_en_la_bitacora(control_app):
    evento = control.registrar_evento(
        control_app, "PRUEBA", actor_tipo="SISTEMA",
        detalle={"token": "x", "client_secret": "y", "codigo_recuperacion": "z", "visible": 1},
    )
    detalle = control_app.execute("SELECT detalle FROM control.auditoria WHERE id = %s", (evento,)).fetchone()["detalle"]
    assert detalle == {"visible": 1}


def test_usuario_del_cliente_no_pertenece_a_dos_clientes(fabrica, control_app):
    ident = fabrica.identidad()
    fabrica.asignacion(ident["id"], "CLIENTE_FINANZAS")
    otro = control_app.execute(
        "INSERT INTO control.tenants (clave, nombre, data_plane_url) VALUES (%s, 'Otro', 'http://otro') RETURNING id",
        (f"OTRO-{uuid4().hex[:6].upper()}",),
    ).fetchone()
    with pytest.raises(psycopg.Error, match="un cliente"):
        control_app.execute(
            "INSERT INTO control.asignaciones (identidad_id, rol, tenant_id, motivo) VALUES (%s, 'CLIENTE_FINANZAS', %s, 'x')",
            (ident["id"], otro["id"]),
        )


def test_rol_no_global_exige_cliente_y_sucursales_validas(fabrica, control_app):
    ident = fabrica.identidad()
    with pytest.raises(psycopg.Error, match="requiere un cliente"):
        control_app.execute(
            "INSERT INTO control.asignaciones (identidad_id, rol, motivo) VALUES (%s, 'CONSULTORA_CAPTURISTA', 'x')",
            (ident["id"],),
        )
    control_app.rollback()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA", sucursales=["INEXISTENTE"])


def test_alcance_por_restaurante_incluye_todas_sus_sucursales(fabrica, control_app):
    ident = fabrica.identidad()
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA", restaurantes=["REST-UNO"], sucursales=["SUR"])
    fila = control_app.execute(
        "SELECT sucursales, restaurantes FROM control.alcance_asignacion WHERE asignacion_id = %s", (asig["id"],)
    ).fetchone()
    assert fila == {"sucursales": ["CENTRO", "NORTE", "SUR"], "restaurantes": ["REST-UNO"]}


def test_sin_restaurantes_ni_sucursales_el_alcance_es_todo(fabrica, control_app):
    ident = fabrica.identidad()
    asig = fabrica.asignacion(ident["id"], "CONSULTORA_CAPTURISTA")
    fila = control_app.execute(
        "SELECT sucursales FROM control.alcance_asignacion WHERE asignacion_id = %s", (asig["id"],)
    ).fetchone()
    assert fila["sucursales"] is None


def test_el_alcance_no_apunta_a_otro_cliente(fabrica, control_app):
    ident = fabrica.identidad()
    global_ = fabrica.asignacion(ident["id"], "CONSULTORA_DIRECTOR", tenant=False)
    with pytest.raises(psycopg.Error, match="cliente de la asignación"):
        control_app.execute(
            "INSERT INTO control.asignacion_sucursales (asignacion_id, tenant_id, sucursal_clave) VALUES (%s, %s, 'NORTE')",
            (global_["id"], fabrica.tenant["id"]),
        )
