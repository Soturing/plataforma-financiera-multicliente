"""Lista de gastos fijos: un proveedor solo puede clasificarse como FIJOS si está dado de alta."""

from typing import Any
from uuid import UUID

from psycopg import Connection

from app.accounting import _audit_catalog
from app.errors import DomainError
from app.periodification import PERIOD_TYPES
from app.provider_catalog import remember_accounting_rule

FIXED_CATEGORY = "FIJOS"


def list_fixed_expenses(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT g.id, g.proveedor_id, p.nombre_normalizado AS proveedor,
               g.subcategoria_id, sc.nombre AS subcategoria,
               g.periodicidad, g.activa, g.actualizado_en
        FROM catalog.gastos_fijos g
        JOIN catalog.proveedores p ON p.id = g.proveedor_id
        LEFT JOIN catalog.subcategorias sc ON sc.id = g.subcategoria_id
        ORDER BY p.nombre_normalizado
        """
    ).fetchall()


def require_fixed_provider(conn: Connection, provider_id: UUID | None) -> None:
    if not provider_id or not conn.execute(
        "SELECT 1 FROM catalog.gastos_fijos WHERE proveedor_id = %s AND activa",
        (provider_id,),
    ).fetchone():
        raise DomainError(
            "Ese proveedor no está en la lista de gastos fijos. Agréguelo primero en Catálogos > Gastos fijos.",
            422,
        )


def save_fixed_expense(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    provider = conn.execute(
        "SELECT id FROM catalog.proveedores WHERE id = %s AND activo", (data["proveedor_id"],)
    ).fetchone()
    if not provider:
        raise DomainError("El proveedor no existe o está inactivo.", 422)
    category = conn.execute(
        "SELECT id FROM catalog.categorias WHERE clave = %s AND activa", (FIXED_CATEGORY,)
    ).fetchone()
    subcategory_id = data.get("subcategoria_id")
    if subcategory_id and not conn.execute(
        "SELECT 1 FROM catalog.subcategorias WHERE id = %s AND categoria_id = %s AND activa",
        (subcategory_id, category["id"]),
    ).fetchone():
        raise DomainError("La subcategoría no pertenece a Gastos fijos.", 422)
    period = data.get("periodicidad") or None
    if period and period not in PERIOD_TYPES:
        raise DomainError("Periodicidad no reconocida.", 422)
    active = bool(data.get("activa", True))

    before = conn.execute(
        "SELECT id, proveedor_id, subcategoria_id, periodicidad, activa FROM catalog.gastos_fijos WHERE proveedor_id = %s",
        (provider["id"],),
    ).fetchone()
    row = conn.execute(
        """
        INSERT INTO catalog.gastos_fijos (proveedor_id, subcategoria_id, periodicidad, activa, creado_por)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (proveedor_id) DO UPDATE
        SET subcategoria_id = EXCLUDED.subcategoria_id, periodicidad = EXCLUDED.periodicidad,
            activa = EXCLUDED.activa, actualizado_en = now()
        RETURNING id, proveedor_id, subcategoria_id, periodicidad, activa
        """,
        (provider["id"], subcategory_id, period, active, actor),
    ).fetchone()
    action = "crear" if not before else (
        "actualizar" if before["activa"] == row["activa"] else ("activar" if active else "desactivar")
    )
    _audit_catalog(
        conn, entity="gasto_fijo", entity_id=row["id"], action=action,
        before=before, after=row, actor=actor,
    )

    if active:
        remember_accounting_rule(
            conn, provider_id=provider["id"], category_id=category["id"],
            subcategory_id=subcategory_id, actor=actor,
        )
        if period:
            conn.execute(
                """
                INSERT INTO catalog.reglas_periodificacion (
                    proveedor_id, subcategoria_id, tipo, activa, aprendida_por
                ) VALUES (%s, %s, %s, true, %s)
                ON CONFLICT (proveedor_id, subcategoria_id)
                DO UPDATE SET tipo = EXCLUDED.tipo, activa = true,
                    aprendida_por = EXCLUDED.aprendida_por, actualizada_en = now()
                """,
                (provider["id"], subcategory_id, period, actor),
            )
    else:
        conn.execute(
            """
            UPDATE catalog.reglas_clasificacion SET activa = false
            WHERE proveedor_id = %s AND activa AND categoria_id = %s
            """,
            (provider["id"], category["id"]),
        )
    return next(item for item in list_fixed_expenses(conn) if item["id"] == row["id"])
