"""Instalación controlada del plano de control (ciclo-vida-usuarios §16).

Uso:
    python -m app.seguridad.instalar cliente
    python -m app.seguridad.instalar director --correo persona@dominio --nombre "Nombre Apellido"
    python -m app.seguridad.instalar reenviar --correo persona@dominio

`cliente` registra este data plane como tenant y copia el registro de sus
sucursales. `director` crea la primera identidad con los roles Director y
Administrador de seguridad (D-020) y le envía la invitación para registrar su
llave física. No crea cuentas genéricas ni contraseñas.
"""
from __future__ import annotations

import argparse
import sys

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.seguridad import control, keycloak_admin


def registrar_cliente() -> dict:
    s = get_settings()
    with psycopg.connect(s.database_url, row_factory=dict_row) as datos:
        sucursales = datos.execute("SELECT id, clave, nombre, activa FROM catalog.sucursales ORDER BY clave").fetchall()
    with control.conexion_control() as conn:
        tenant = conn.execute(
            """
            INSERT INTO control.tenants (clave, nombre, data_plane_url) VALUES (%s, %s, %s)
            ON CONFLICT (clave) DO UPDATE SET nombre = EXCLUDED.nombre, data_plane_url = EXCLUDED.data_plane_url
            RETURNING *
            """,
            (s.tenant_clave, s.tenant_nombre, s.app_url),
        ).fetchone()
        for suc in sucursales:
            conn.execute(
                """
                INSERT INTO control.sucursales (tenant_id, clave, nombre, data_plane_id, activa) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, clave) DO UPDATE
                SET nombre = EXCLUDED.nombre, data_plane_id = EXCLUDED.data_plane_id, activa = EXCLUDED.activa
                """,
                (tenant["id"], suc["clave"], suc["nombre"], suc["id"], suc["activa"]),
            )
        control.registrar_evento(
            conn, "ALTA_CLIENTE", actor_tipo="SISTEMA", tenant_id=tenant["id"], modulo="CLIENTES", accion="ADMINISTRAR",
            detalle={"sucursales": [x["clave"] for x in sucursales], "origen": "instalacion"},
        )
    return {"tenant": tenant["clave"], "sucursales": [x["clave"] for x in sucursales]}


def crear_director(correo: str, nombre: str) -> dict:
    with control.conexion_control() as conn:
        tenant = control.tenant_por_clave(conn, get_settings().tenant_clave)
        if tenant is None:
            raise SystemExit("Primero registre el cliente: python -m app.seguridad.instalar cliente")
        if conn.execute(
            "SELECT 1 FROM control.asignaciones WHERE rol = 'CONSULTORA_DIRECTOR' AND estado IN ('ACTIVA', 'PENDIENTE')"
        ).fetchone():
            raise SystemExit("Ya existe un director. Las siguientes personas se invitan desde la aplicación.")
        user_id = keycloak_admin.buscar_usuario(correo) or keycloak_admin.crear_usuario(correo, nombre, llave_fisica=True)
        keycloak_admin.fijar_llave_fisica(user_id, True)
        ident = conn.execute(
            "INSERT INTO control.identidades (idp_subject, correo, nombre, estado) VALUES (%s, %s, %s, 'INVITADA') RETURNING id",
            (user_id, correo, nombre),
        ).fetchone()
        for rol in ("CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD"):
            conn.execute(
                "INSERT INTO control.asignaciones (identidad_id, rol, tenant_id, motivo) VALUES (%s, %s, NULL, %s)",
                (ident["id"], rol, "Instalación inicial; excepción temporal D-020"),
            )
        keycloak_admin.enviar_invitacion(user_id, llave_fisica=True)
        control.registrar_evento(
            conn, "INSTALACION_DIRECTOR", actor_tipo="SISTEMA", tenant_id=tenant["id"], modulo="IDENTIDADES",
            accion="ADMINISTRAR", recurso_tipo="identidad", recurso_id=str(ident["id"]), sensibilidad="C3",
            motivo="Primer director (ciclo-vida §16) con excepción D-020",
            detalle={"roles": ["CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD"]},
        )
    return {"identidad_id": str(ident["id"]), "correo": correo, "invitacion": "enviada"}


def reenviar_invitacion(correo: str) -> dict:
    """Nueva invitación de un solo uso (la anterior caduca a las 24 h y no se reactiva)."""
    with control.conexion_control() as conn:
        ident = conn.execute(
            "SELECT * FROM control.identidades WHERE lower(correo) = lower(%s)", (correo,)
        ).fetchone()
        if ident is None or ident["estado"] not in ("INVITADA", "REGISTRO_PENDIENTE"):
            raise SystemExit("Sólo se reenvía a personas invitadas que aún no se activan.")
        privilegiada = conn.execute(
            """SELECT bool_or(r.privilegiado) AS p FROM control.asignaciones a JOIN control.roles r ON r.codigo = a.rol
               WHERE a.identidad_id = %s AND a.estado = 'ACTIVA'""",
            (ident["id"],),
        ).fetchone()["p"] or False
        keycloak_admin.enviar_invitacion(ident["idp_subject"], llave_fisica=privilegiada)
        control.registrar_evento(
            conn, "INVITACION_REENVIADA", actor_tipo="SISTEMA", modulo="IDENTIDADES", accion="ADMINISTRAR",
            recurso_tipo="identidad", recurso_id=str(ident["id"]),
        )
    return {"correo": correo, "invitacion": "reenviada", "llave_fisica": privilegiada}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seguridad.instalar")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("cliente", help="Registra este data plane como cliente y sincroniza sus sucursales")
    d = sub.add_parser("director", help="Crea al primer director e envía su invitación")
    d.add_argument("--correo", required=True)
    d.add_argument("--nombre", required=True)
    r = sub.add_parser("reenviar", help="Envía una nueva invitación a una persona que aún no se activa")
    r.add_argument("--correo", required=True)
    args = parser.parse_args(argv)
    if args.comando == "cliente":
        resultado = registrar_cliente()
    elif args.comando == "director":
        resultado = crear_director(args.correo, args.nombre)
    else:
        resultado = reenviar_invitacion(args.correo)
    print(resultado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
