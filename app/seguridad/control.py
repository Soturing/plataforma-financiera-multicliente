"""Acceso a la base del plano de control y registro de auditoría.

La aplicación se conecta con `control_app`: puede leer y escribir identidades,
asignaciones y sesiones, pero sólo puede anexar a la auditoría.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.errors import DomainError

# Campos que nunca deben llegar a la bitácora (auditoria-alertas §3).
_PROHIBIDOS = ("password", "contrasena", "token", "secret", "secreto", "codigo_recuperacion", "verifier", "cookie")


def ip_cliente(request) -> str | None:
    """IP del cliente sólo si es una dirección válida (la columna es inet)."""
    import ipaddress

    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def control_configurado() -> bool:
    return bool(get_settings().control_database_url)


@contextmanager
def conexion_control() -> Iterator[Connection]:
    url = get_settings().control_database_url
    if not url:
        raise DomainError("El plano de control no está configurado (FACTURAS_CONTROL_DATABASE_URL).", 503)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


def registrar_evento(
    conn: Connection,
    tipo: str,
    resultado: str = "EXITO",
    *,
    actor_id: UUID | None = None,
    actor_tipo: str = "PERSONA",
    rol: str | None = None,
    tenant_id: UUID | None = None,
    modulo: str | None = None,
    sucursal: str | None = None,
    accion: str | None = None,
    recurso_tipo: str | None = None,
    recurso_id: str | None = None,
    sesion_id: UUID | None = None,
    metodo_auth: str | None = None,
    ip: str | None = None,
    motivo: str | None = None,
    peticion_id: str | None = None,
    sensibilidad: str | None = None,
    politica: str | None = None,
    detalle: dict[str, Any] | None = None,
) -> int:
    """Anexa un evento. Una operación sensible no está completa sin su evento (§6)."""
    limpio = {k: v for k, v in (detalle or {}).items() if not any(p in k.lower() for p in _PROHIBIDOS)}
    fila = conn.execute(
        """
        INSERT INTO control.auditoria (
            tipo, resultado, actor_id, actor_tipo, rol, tenant_id, modulo, sucursal, accion,
            recurso_tipo, recurso_id, sesion_id, metodo_auth, ip, motivo, peticion_id,
            sensibilidad, politica, detalle
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tipo, resultado, actor_id, actor_tipo, rol, tenant_id, modulo, sucursal, accion,
            recurso_tipo, recurso_id, sesion_id, metodo_auth, ip, motivo, peticion_id,
            sensibilidad, politica, Jsonb(limpio),
        ),
    ).fetchone()
    return fila["id"]


# --------------------------------------------------------------------------- #
# Tenants y sucursales


def tenant_por_clave(conn: Connection, clave: str) -> dict | None:
    return conn.execute("SELECT * FROM control.tenants WHERE clave = %s", (clave,)).fetchone()


def sucursales_tenant(conn: Connection, tenant_id: UUID) -> list[dict]:
    return conn.execute(
        "SELECT clave, nombre, restaurante_clave, data_plane_id, activa FROM control.sucursales WHERE tenant_id = %s ORDER BY clave",
        (tenant_id,),
    ).fetchall()


def restaurantes_tenant(conn: Connection, tenant_id: UUID) -> list[dict]:
    return conn.execute(
        "SELECT clave, nombre, activo FROM control.restaurantes WHERE tenant_id = %s ORDER BY nombre",
        (tenant_id,),
    ).fetchall()


def ids_data_plane(conn: Connection, tenant_id: UUID, claves: list[str]) -> list[str]:
    """UUID de catalog.sucursales en la base del cliente, para el alcance RLS."""
    filas = conn.execute(
        "SELECT data_plane_id::text AS id FROM control.sucursales WHERE tenant_id = %s AND clave = ANY(%s)",
        (tenant_id, claves),
    ).fetchall()
    return [f["id"] for f in filas]


def guardar_alcance(conn: Connection, asignacion_id: UUID, tenant_id: UUID,
                    restaurantes: list[str] | None, sucursales: list[str] | None) -> None:
    for clave in restaurantes or []:
        conn.execute(
            "INSERT INTO control.asignacion_restaurantes (asignacion_id, tenant_id, restaurante_clave) VALUES (%s, %s, %s)",
            (asignacion_id, tenant_id, clave),
        )
    for clave in sucursales or []:
        conn.execute(
            "INSERT INTO control.asignacion_sucursales (asignacion_id, tenant_id, sucursal_clave) VALUES (%s, %s, %s)",
            (asignacion_id, tenant_id, clave),
        )


# --------------------------------------------------------------------------- #
# Identidades y asignaciones


def identidad_por_subject(conn: Connection, subject: str) -> dict | None:
    return conn.execute("SELECT * FROM control.identidades WHERE idp_subject = %s", (subject,)).fetchone()


def identidad(conn: Connection, identidad_id: UUID) -> dict | None:
    return conn.execute("SELECT * FROM control.identidades WHERE id = %s", (identidad_id,)).fetchone()


def asignaciones_vigentes(conn: Connection, identidad_id: UUID) -> list[dict]:
    """Asignaciones activas y dentro de su vigencia; marca como expiradas las vencidas."""
    conn.execute(
        """
        UPDATE control.asignaciones SET estado = 'EXPIRADA'
        WHERE identidad_id = %s AND estado = 'ACTIVA' AND vigente_hasta IS NOT NULL AND vigente_hasta <= now()
        """,
        (identidad_id,),
    )
    return conn.execute(
        """
        SELECT a.*, al.sucursales, al.restaurantes, r.nombre AS rol_nombre, r.privilegiado, r.global AS rol_global,
               t.clave AS tenant_clave, t.nombre AS tenant_nombre, t.estado AS tenant_estado
        FROM control.asignaciones a
        JOIN control.alcance_asignacion al ON al.asignacion_id = a.id
        JOIN control.roles r ON r.codigo = a.rol
        LEFT JOIN control.tenants t ON t.id = a.tenant_id
        WHERE a.identidad_id = %s AND a.estado = 'ACTIVA' AND a.vigente_desde <= now()
        ORDER BY r.privilegiado DESC, a.creado_en
        """,
        (identidad_id,),
    ).fetchall()


def listar_identidades(conn: Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT i.id, i.correo, i.nombre, i.estado, i.creado_en, i.ultimo_acceso_en,
               coalesce(json_agg(json_build_object(
                   'id', a.id, 'rol', a.rol, 'tenant', t.clave, 'modulos', a.modulos,
                   'sucursales', al.sucursales, 'restaurantes', al.restaurantes, 'condicionados', a.condicionados,
                   'estado', a.estado, 'vigente_hasta', a.vigente_hasta
               ) ORDER BY a.creado_en) FILTER (WHERE a.id IS NOT NULL), '[]') AS asignaciones,
               (SELECT count(*) FROM control.sesiones s
                 WHERE s.identidad_id = i.id AND s.revocada_en IS NULL AND s.expira_absoluta > now()) AS sesiones_abiertas
        FROM control.identidades i
        LEFT JOIN control.asignaciones a ON a.identidad_id = i.id AND a.estado IN ('ACTIVA', 'PENDIENTE')
        LEFT JOIN control.alcance_asignacion al ON al.asignacion_id = a.id
        LEFT JOIN control.tenants t ON t.id = a.tenant_id
        GROUP BY i.id
        ORDER BY i.nombre
        """
    ).fetchall()


def listar_auditoria(conn: Connection, *, tenant_id: UUID | None, actor_id: UUID | None, limite: int = 100) -> list[dict]:
    """Eventos recientes. `tenant_id`/`actor_id` restringen el alcance (auditoria-alertas §9)."""
    filtros, params = [], []
    if tenant_id is not None:
        filtros.append("a.tenant_id = %s")
        params.append(tenant_id)
    if actor_id is not None:
        filtros.append("a.actor_id = %s")
        params.append(actor_id)
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    params.append(limite)
    return conn.execute(
        f"""
        SELECT a.id, a.ocurrido_en, a.tipo, a.resultado, a.actor_tipo, i.nombre AS actor, i.correo AS actor_correo,
               a.rol, t.clave AS tenant, a.modulo, a.sucursal, a.accion, a.recurso_tipo, a.recurso_id,
               a.motivo, a.metodo_auth, a.detalle
        FROM control.auditoria a
        LEFT JOIN control.identidades i ON i.id = a.actor_id
        LEFT JOIN control.tenants t ON t.id = a.tenant_id
        {where}
        ORDER BY a.id DESC LIMIT %s
        """,  # nosec B608
        # Motivo: filtros armados con literales del código; los valores van como parámetros
        params,
    ).fetchall()


def verificar_auditoria(conn: Connection) -> dict:
    roto = conn.execute("SELECT * FROM control.verificar_auditoria()").fetchone()
    total = conn.execute("SELECT count(*) AS n FROM control.auditoria").fetchone()["n"]
    return {"eventos": total, "integra": roto is None, "primer_problema": roto}
