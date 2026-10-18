"""Razones sociales del propio grupo (receptores de las facturas)."""

import re
from typing import Any

from psycopg import Connection

from app.errors import DomainError
from app.rfc import GENERIC_RFCS


def list_own_entities(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT id, nombre, rfc, activa, creado_en FROM catalog.entidades_propias ORDER BY nombre"
    ).fetchall()


def save_own_entity(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    name = " ".join(str(data["nombre"]).split())
    rfc = re.sub(r"[\s\-]", "", str(data.get("rfc") or "")).upper() or None
    if len(name) < 4:
        raise DomainError("El nombre debe tener al menos 4 caracteres.", 422)
    if rfc and (rfc in GENERIC_RFCS or not re.fullmatch(r"[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}", rfc)):
        raise DomainError("El RFC no tiene un formato válido.", 422)
    row = conn.execute(
        """
        INSERT INTO catalog.entidades_propias (nombre, rfc, activa, creado_por)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (nombre) DO UPDATE SET rfc = EXCLUDED.rfc, activa = EXCLUDED.activa
        RETURNING id, nombre, rfc, activa, creado_en
        """,
        (name, rfc, bool(data.get("activa", True)), actor),
    ).fetchone()
    return row
