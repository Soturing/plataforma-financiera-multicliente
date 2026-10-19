"""Tareas periódicas de seguridad (ciclo-vida-usuarios §12).

Uso (programar una vez al día):
    python -m app.seguridad.mantenimiento inactividad

- Roles globales sin actividad durante 30 días y el resto durante 90: suspensión preventiva.
- Aviso siete días antes, una vez por ciclo.
- La reactivación la hace una persona administradora desde "Usuarios y accesos".
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from psycopg import Connection

from app.seguridad import control, keycloak_admin, notificaciones, sesiones
from app.seguridad.politica import ROLES_GLOBALES

LIMITE_GLOBAL = timedelta(days=30)
LIMITE_NORMAL = timedelta(days=90)
AVISO_ANTES = timedelta(days=7)


def revisar_inactividad(conn: Connection, ahora: datetime | None = None, *, deshabilitar_idp: bool = True) -> dict:
    ahora = ahora or datetime.now(timezone.utc)
    personas = conn.execute(
        """
        SELECT i.*, greatest(coalesce(i.ultimo_acceso_en, i.creado_en), i.creado_en) AS ultima_actividad,
               EXISTS (SELECT 1 FROM control.asignaciones a WHERE a.identidad_id = i.id AND a.estado = 'ACTIVA'
                       AND a.rol = ANY(%s)) AS global
        FROM control.identidades i
        WHERE i.estado = 'ACTIVA'
        """,
        (list(ROLES_GLOBALES),),
    ).fetchall()
    avisadas, suspendidas = [], []
    for p in personas:
        limite = LIMITE_GLOBAL if p["global"] else LIMITE_NORMAL
        inactiva = ahora - p["ultima_actividad"]
        vence = p["ultima_actividad"] + limite
        if inactiva >= limite:
            conn.execute(
                "UPDATE control.identidades SET estado = 'SUSPENDIDA', motivo_estado = 'Inactividad', actualizado_en = now() "
                "WHERE id = %s",
                (p["id"],),
            )
            cerradas = sesiones.revocar_todas(conn, p["id"], "Suspensión preventiva por inactividad")
            if deshabilitar_idp and p["idp_subject"]:
                keycloak_admin.deshabilitar(p["idp_subject"])
            control.registrar_evento(
                conn, "SUSPENSION_INACTIVIDAD", actor_tipo="SISTEMA", recurso_tipo="identidad", recurso_id=str(p["id"]),
                modulo="IDENTIDADES", accion="ADMINISTRAR", motivo="Inactividad",
                detalle={"dias_inactiva": inactiva.days, "limite_dias": limite.days, "sesiones_revocadas": cerradas},
            )
            notificaciones.a_persona(conn, p, "SUSPENSION_INACTIVIDAD")
            suspendidas.append(p["correo"])
        elif inactiva >= limite - AVISO_ANTES and (
            p["aviso_inactividad_en"] is None or p["aviso_inactividad_en"] < p["ultima_actividad"]
        ):
            conn.execute("UPDATE control.identidades SET aviso_inactividad_en = %s WHERE id = %s", (ahora, p["id"]))
            control.registrar_evento(
                conn, "AVISO_INACTIVIDAD", actor_tipo="SISTEMA", recurso_tipo="identidad", recurso_id=str(p["id"]),
                modulo="IDENTIDADES", detalle={"dias_inactiva": inactiva.days, "vence": vence.isoformat()},
            )
            notificaciones.a_persona(conn, p, "AVISO_INACTIVIDAD", detalle=vence.astimezone().strftime("%d/%m/%Y"))
            avisadas.append(p["correo"])
    return {"revisadas": len(personas), "avisadas": avisadas, "suspendidas": suspendidas}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.seguridad.mantenimiento")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("inactividad", help="Avisa y suspende cuentas sin actividad")
    parser.parse_args(argv)
    with control.conexion_control() as conn:
        print(revisar_inactividad(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
