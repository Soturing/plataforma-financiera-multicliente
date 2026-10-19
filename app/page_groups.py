"""Páginas de una misma factura.

Cuando un lote trae una factura de varias páginas, la página sin totales (continuación) se liga a la
página principal (la que sí trae el total) del mismo proveedor y folio. La continuación sale de la bandeja
y la revisión humana ve ambas desde el documento principal; "separar" deshace la decisión.
"""

from typing import Any
from uuid import UUID

from psycopg import Connection

from app.errors import DomainError

ACTIVE_CONTINUATION_SQL = (
    "NOT EXISTS (SELECT 1 FROM core.documentos_continuacion dc "
    "WHERE dc.factura_continuacion_id = f.id AND dc.estado = 'activa')"
)


def group_batch_pages(conn: Connection, batch_id: UUID | None) -> list[dict[str, Any]]:
    """Liga las páginas de continuación del lote a su principal. Es idempotente y respeta lo separado a mano."""
    if batch_id is None:
        return []
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (str(batch_id),))
    rows = conn.execute(
        """
        SELECT f.id, f.pagina_origen, f.archivo_nombre, i.id AS interpretacion_id,
               i.proveedor_id, i.folio, i.folio_origen, i.total
        FROM core.facturas f
        JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        WHERE f.lote_id = %s
          AND f.estado::text IN ('requiere_revision', 'ocr_completado', 'validando')
          AND i.proveedor_id IS NOT NULL AND i.folio_origen = 'detectado' AND i.folio IS NOT NULL
        ORDER BY f.pagina_origen
        """,
        (batch_id,),
    ).fetchall()
    groups: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["proveedor_id"], str(row["folio"]).strip().upper()), []).append(row)

    created = []
    for (_, folio), members in groups.items():
        complete = [m for m in members if m["total"] is not None]
        incomplete = [m for m in members if m["total"] is None]
        if not complete or not incomplete:
            continue  # sin una página principal con total no hay a qué ligar; con totales en ambas, es otro caso
        principal = complete[0]
        for page in incomplete:
            row = conn.execute(
                """
                INSERT INTO core.documentos_continuacion (
                    factura_principal_id, factura_continuacion_id, criterio, valor_coincidente
                ) VALUES (%s, %s, 'folio', %s)
                ON CONFLICT (factura_continuacion_id) DO NOTHING
                RETURNING id
                """,
                (principal["id"], page["id"], folio),
            ).fetchone()
            if not row:
                continue
            with conn.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO core.validaciones
                        (factura_id, interpretacion_id, codigo, severidad, aprobada, campo, mensaje)
                    VALUES (%s, %s, %s, 'informativa', true, NULL, %s)
                    """,
                    [
                        (page["id"], page["interpretacion_id"], "CONTINUACION",
                         f"Página de continuación de {principal['archivo_nombre']} (folio {folio}); se revisa desde el documento principal"),
                        (principal["id"], principal["interpretacion_id"], "PAGINAS_RELACIONADAS",
                         f"Incluye la página {page['pagina_origen'] or page['archivo_nombre']} (folio {folio}) sin totales"),
                    ],
                )
            created.append({"principal": principal["id"], "continuacion": page["id"], "folio": folio})
    return created


def related_pages(conn: Connection, invoice_id: UUID) -> list[dict[str, Any]]:
    """Páginas ligadas al documento: sus continuaciones (si es principal) o su principal (si es continuación)."""
    return conn.execute(
        """
        SELECT dc.id AS vinculo_id, 'continuacion' AS rol, f.id, f.archivo_nombre, f.archivo_url,
               f.pagina_origen, dc.valor_coincidente AS folio, dc.estado
        FROM core.documentos_continuacion dc JOIN core.facturas f ON f.id = dc.factura_continuacion_id
        WHERE dc.factura_principal_id = %s
        UNION ALL
        SELECT dc.id, 'principal', f.id, f.archivo_nombre, f.archivo_url, f.pagina_origen, dc.valor_coincidente, dc.estado
        FROM core.documentos_continuacion dc JOIN core.facturas f ON f.id = dc.factura_principal_id
        WHERE dc.factura_continuacion_id = %s
        ORDER BY pagina_origen NULLS LAST
        """,
        (invoice_id, invoice_id),
    ).fetchall()


def separate_continuation(conn: Connection, link_id: UUID, actor: str) -> dict[str, Any]:
    row = conn.execute(
        """
        UPDATE core.documentos_continuacion
        SET estado = 'separada', resuelto_en = now(), resuelto_por = %s
        WHERE id = %s AND estado = 'activa'
        RETURNING id, factura_principal_id, factura_continuacion_id
        """,
        (actor, link_id),
    ).fetchone()
    if not row:
        raise DomainError("El vínculo no existe o ya fue separado.", 404)
    return row
