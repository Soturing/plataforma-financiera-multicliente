import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.errors import DomainError
from app.schemas import ProcesamientoSimulado
from app.pdf_splitter import SplitPage
from app.classification import classify_document, is_expense_document, save_classification
from app.provider_catalog import normalize_alias, remember_accounting_rule, remember_provider_alias
from app.periodification import save_periodification


REVIEW_SELECT = """
SELECT
    f.id, f.estado::text, f.recibida_en, f.archivo_nombre, f.archivo_url,
    s.nombre AS sucursal, s.restaurante,
    i.id AS interpretacion_id,
    COALESCE(p.nombre_normalizado, i.proveedor_propuesto) AS proveedor,
    i.folio, i.folio_origen, i.fecha_emision, i.subtotal, i.iva, i.total,
    c.nombre AS categoria, sc.nombre AS subcategoria, i.confianza,
    cd.tipo::text AS tipo_documento, cd.confianza AS confianza_clasificacion,
    (
        SELECT count(*)::integer FROM core.validaciones v
        WHERE v.interpretacion_id = i.id AND NOT v.aprobada AND v.severidad = 'error'
    ) AS validaciones_fallidas
FROM core.facturas f
JOIN catalog.sucursales s ON s.id = f.sucursal_id
LEFT JOIN LATERAL (
    SELECT * FROM ai.interpretaciones ix
    WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
) i ON true
LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id
LEFT JOIN catalog.categorias c ON c.id = i.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = i.subcategoria_id
LEFT JOIN LATERAL (
    SELECT tipo, confianza FROM core.clasificaciones_documentales cdx
    WHERE cdx.factura_id = f.id ORDER BY cdx.version DESC LIMIT 1
) cd ON true
"""


def create_invoice(
    conn: Connection,
    *,
    sucursal_clave: str,
    filename: str,
    mime: str,
    file_path: str,
    sha256: str,
    created_by: str,
) -> dict[str, Any]:
    duplicate = conn.execute(
        """
        SELECT id, estado::text, archivo_nombre
        FROM core.facturas
        WHERE archivo_sha256 = %s
        ORDER BY recibida_en DESC
        LIMIT 1
        """,
        (sha256,),
    ).fetchone()
    if duplicate:
        raise DomainError(
            f"Documento duplicado: ya existe como {duplicate['archivo_nombre']} "
            f"({duplicate['estado']}).",
            409,
        )
    row = conn.execute(
        """
        INSERT INTO core.facturas (
            sucursal_id, archivo_url, archivo_nombre, archivo_mime,
            archivo_sha256, creada_por
        )
        SELECT id, %s, %s, %s, %s, %s
        FROM catalog.sucursales WHERE clave = %s AND activa
        RETURNING id, estado::text, archivo_nombre
        """,
        (file_path, filename, mime, sha256, created_by, sucursal_clave),
    ).fetchone()
    if not row:
        raise DomainError(f"No existe una sucursal activa con clave {sucursal_clave}.", 422)
    return row


def find_invoice_by_sha256(conn: Connection, sha256: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, estado::text, archivo_nombre, archivo_url
        FROM core.facturas
        WHERE archivo_sha256 = %s
        ORDER BY recibida_en ASC, id ASC
        LIMIT 1
        """,
        (sha256,),
    ).fetchone()


def register_hash_duplicate(
    conn: Connection,
    *,
    original_invoice_id: UUID,
    filename: str,
    file_path: str,
    sha256: str,
) -> dict[str, Any]:
    return conn.execute(
        """
        INSERT INTO core.documentos_duplicados (
            factura_original_id, archivo_url, archivo_nombre, archivo_sha256,
            criterio, valor_coincidente
        ) VALUES (%s, %s, %s, %s, 'sha256', %s)
        RETURNING id, criterio, estado, archivo_nombre
        """,
        (original_invoice_id, file_path, filename, sha256, sha256),
    ).fetchone()


def register_uuid_duplicates(conn: Connection, uuid_fiscal: UUID) -> list[dict[str, Any]]:
    candidates = conn.execute(
        """
        SELECT f.id, f.estado::text, f.archivo_nombre, f.archivo_url,
               f.archivo_sha256, f.archivo_mime, f.recibida_en,
               EXISTS (
                   SELECT 1 FROM core.facturas_finales ff
                   WHERE ff.factura_id = f.id AND ff.vigente
               ) AS aprobada
        FROM core.facturas f
        JOIN LATERAL (
            SELECT uuid_fiscal FROM ai.interpretaciones ix
            WHERE ix.factura_id = f.id
            ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        WHERE i.uuid_fiscal = %s AND f.estado <> 'rechazada'
        ORDER BY aprobada DESC,
                 (f.archivo_mime IN ('application/xml', 'text/xml')) DESC,
                 f.recibida_en ASC, f.id ASC
        """,
        (uuid_fiscal,),
    ).fetchall()
    if len(candidates) < 2:
        return []
    original = candidates[0]
    registered = []
    for duplicate in candidates[1:]:
        if duplicate["aprobada"]:
            continue
        row = conn.execute(
            """
            INSERT INTO core.documentos_duplicados (
                factura_original_id, factura_duplicada_id, archivo_url,
                archivo_nombre, archivo_sha256, criterio, valor_coincidente
            ) VALUES (%s, %s, %s, %s, %s, 'uuid_fiscal', %s)
            ON CONFLICT (factura_duplicada_id, criterio)
                WHERE factura_duplicada_id IS NOT NULL AND estado = 'pendiente'
            DO NOTHING
            RETURNING id, factura_duplicada_id
            """,
            (
                original["id"], duplicate["id"], duplicate["archivo_url"],
                duplicate["archivo_nombre"], duplicate["archivo_sha256"],
                str(uuid_fiscal),
            ),
        ).fetchone()
        if row:
            registered.append(row)
    return registered


def list_document_duplicates(conn: Connection) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT d.id, d.criterio, d.valor_coincidente, d.detectado_en,
               d.archivo_nombre AS archivo_duplicado,
               d.factura_duplicada_id,
               d.factura_original_id,
               fo.archivo_nombre AS archivo_original,
               fo.estado::text AS estado_original,
               COALESCE(p.nombre_normalizado, io.proveedor_propuesto) AS proveedor,
               io.folio, io.fecha_emision, io.total,
               so.nombre AS sucursal
        FROM core.documentos_duplicados d
        JOIN core.facturas fo ON fo.id = d.factura_original_id
        JOIN catalog.sucursales so ON so.id = fo.sucursal_id
        LEFT JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix
            WHERE ix.factura_id = fo.id ORDER BY ix.version DESC LIMIT 1
        ) io ON true
        LEFT JOIN catalog.proveedores p ON p.id = io.proveedor_id
        WHERE d.estado = 'pendiente'
        ORDER BY d.detectado_en DESC
        """
    ).fetchall()


def discard_document_duplicates(
    conn: Connection, duplicate_ids: list[UUID], actor: str
) -> list[dict[str, Any]]:
    discarded = []
    for duplicate_id in duplicate_ids:
        row = conn.execute(
            """
            SELECT id, factura_duplicada_id, archivo_url, archivo_nombre
            FROM core.documentos_duplicados
            WHERE id = %s AND estado = 'pendiente'
            FOR UPDATE
            """,
            (duplicate_id,),
        ).fetchone()
        if not row:
            continue
        if row["factura_duplicada_id"]:
            invoice = conn.execute(
                "SELECT estado::text FROM core.facturas WHERE id = %s FOR UPDATE",
                (row["factura_duplicada_id"],),
            ).fetchone()
            if invoice and invoice["estado"] == "aprobada":
                raise DomainError("No se puede descartar una factura ya aprobada.", 409)
            conn.execute(
                """
                UPDATE core.facturas
                SET estado = 'rechazada', actualizada_en = now(),
                    error_codigo = 'DUPLICADO_DESCARTADO',
                    error_detalle = 'Descartado desde la bandeja de duplicados'
                WHERE id = %s
                """,
                (row["factura_duplicada_id"],),
            )
        conn.execute(
            """
            UPDATE core.documentos_duplicados
            SET estado = 'descartado', resuelto_en = now(), resuelto_por = %s
            WHERE id = %s
            """,
            (actor, duplicate_id),
        )
        discarded.append(row)
    return discarded


def create_batch(
    conn: Connection,
    *,
    batch_id: UUID,
    sucursal_clave: str,
    original_path: str,
    original_name: str,
    original_sha256: str,
    created_by: str,
    pages: list[SplitPage],
) -> dict[str, Any]:
    branch = conn.execute(
        "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa",
        (sucursal_clave,),
    ).fetchone()
    if not branch:
        raise DomainError(f"No existe una sucursal activa con clave {sucursal_clave}.", 422)

    conn.execute(
        """
        INSERT INTO core.lotes_carga (
            id, sucursal_id, estado, archivo_original_url, archivo_original_nombre,
            archivo_sha256, total_paginas, creado_por, completado_en
        ) VALUES (%s, %s, 'listo', %s, %s, %s, %s, %s, now())
        """,
        (
            batch_id, branch["id"], original_path, original_name,
            original_sha256, len(pages), created_by,
        ),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.facturas (
                sucursal_id, canal, estado, archivo_url, archivo_nombre,
                archivo_mime, archivo_sha256, creada_por, lote_id, pagina_origen
            ) VALUES (%s, 'carga_masiva', 'recibida', %s, %s, 'application/pdf', %s, %s, %s, %s)
            """,
            [
                (
                    branch["id"], str(page.path.resolve()),
                    f"{original_name} - página {page.number}", page.sha256,
                    created_by, batch_id, page.number,
                )
                for page in pages
            ],
        )
    return {
        "id": batch_id,
        "estado": "listo",
        "total_paginas": len(pages),
        "facturas_creadas": len(pages),
    }


def list_batches(conn: Connection, limit: int = 20) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT
            l.id, l.estado::text, l.archivo_original_nombre, l.total_paginas,
            l.creado_por, l.creado_en, s.nombre AS sucursal, s.restaurante,
            count(f.id) FILTER (WHERE f.estado = 'recibida')::integer AS recibidas,
            count(f.id) FILTER (WHERE f.estado IN ('ocr_procesando','ocr_completado','ia_procesando','ia_completada','validando'))::integer AS procesando,
            count(f.id) FILTER (WHERE f.estado = 'requiere_revision')::integer AS revision,
            count(f.id) FILTER (WHERE f.estado = 'aprobada')::integer AS aprobadas,
            count(f.id) FILTER (WHERE f.estado = 'rechazada')::integer AS rechazadas,
            count(f.id) FILTER (WHERE f.estado = 'error')::integer AS errores
        FROM core.lotes_carga l
        JOIN catalog.sucursales s ON s.id = l.sucursal_id
        LEFT JOIN core.facturas f ON f.lote_id = l.id
        GROUP BY l.id, s.nombre, s.restaurante
        ORDER BY l.creado_en DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


def cancel_batch(conn: Connection, batch_id: UUID, actor: str) -> dict[str, Any]:
    batch = conn.execute(
        """
        SELECT id, estado::text, archivo_original_nombre
        FROM core.lotes_carga WHERE id = %s FOR UPDATE
        """,
        (batch_id,),
    ).fetchone()
    if not batch:
        raise DomainError("Lote no encontrado.", 404)
    if batch["estado"] == "cancelado":
        return {"lote_id": batch_id, "canceladas": 0, "estado": "cancelado"}
    rows = conn.execute(
        """
        UPDATE core.facturas
        SET estado = 'cancelada', error_codigo = 'CANCELADO_POR_USUARIO',
            error_detalle = %s, actualizada_en = now()
        WHERE lote_id = %s AND estado NOT IN ('aprobada', 'rechazada', 'cancelada')
        RETURNING id
        """,
        (f"Procesamiento cancelado por {actor}", batch_id),
    ).fetchall()
    conn.execute(
        """
        UPDATE core.lotes_carga
        SET estado = 'cancelado', completado_en = now(), error_detalle = %s
        WHERE id = %s
        """,
        (f"Cancelado por {actor}", batch_id),
    )
    return {"lote_id": batch_id, "canceladas": len(rows), "estado": "cancelado"}


def delete_pending_invoices(
    conn: Connection,
    invoice_ids: list[UUID],
    actor: str,
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(invoice_ids))
    rows = conn.execute(
        """
        SELECT id, lote_id, archivo_nombre, archivo_url, estado::text
        FROM core.facturas
        WHERE id = ANY(%s::uuid[])
        FOR UPDATE
        """,
        (unique_ids,),
    ).fetchall()
    if len(rows) != len(unique_ids):
        raise DomainError("Uno o más documentos ya no existen.", 404)
    protected = [row for row in rows if row["estado"] in {"aprobada", "rechazada"}]
    if protected:
        raise DomainError("No se pueden eliminar documentos aprobados o rechazados desde la bandeja.", 409)
    final_count = conn.execute(
        "SELECT count(*) AS total FROM core.facturas_finales WHERE factura_id = ANY(%s::uuid[])",
        (unique_ids,),
    ).fetchone()["total"]
    if final_count:
        raise DomainError("Hay documentos publicados en Analytics; no se pueden eliminar.", 409)

    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO audit.documentos_eliminados (
                factura_id, lote_id, archivo_nombre, estado_anterior, archivo_url, eliminado_por
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (row["id"], row["lote_id"], row["archivo_nombre"], row["estado"], row["archivo_url"], actor)
                for row in rows
            ],
        )
    conn.execute(
        "DELETE FROM core.documentos_duplicados WHERE factura_original_id = ANY(%s::uuid[]) OR factura_duplicada_id = ANY(%s::uuid[])",
        (unique_ids, unique_ids),
    )
    conn.execute("DELETE FROM core.facturas WHERE id = ANY(%s::uuid[])", (unique_ids,))

    batch_ids = list({row["lote_id"] for row in rows if row["lote_id"]})
    removed_batches = []
    for batch_id in batch_ids:
        remaining = conn.execute(
            "SELECT count(*) AS total FROM core.facturas WHERE lote_id = %s",
            (batch_id,),
        ).fetchone()["total"]
        if remaining:
            conn.execute(
                "UPDATE core.lotes_carga SET total_paginas = %s WHERE id = %s",
                (remaining, batch_id),
            )
        else:
            batch = conn.execute(
                "DELETE FROM core.lotes_carga WHERE id = %s RETURNING archivo_original_url",
                (batch_id,),
            ).fetchone()
            if batch:
                removed_batches.append(batch["archivo_original_url"])
    return {
        "eliminados": len(rows),
        "archivos": [row["archivo_url"] for row in rows],
        "lotes_eliminados": removed_batches,
    }


def _invoice_for_processing(conn: Connection, invoice_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, estado::text FROM core.facturas WHERE id = %s FOR UPDATE",
        (invoice_id,),
    ).fetchone()
    if not row:
        raise DomainError("Factura no encontrada.", 404)
    if row["estado"] not in {"recibida", "error"}:
        raise DomainError(f"La factura no puede procesarse desde el estado {row['estado']}.", 409)
    return row


def process_simulated(conn: Connection, invoice_id: UUID, data: ProcesamientoSimulado) -> dict[str, Any]:
    _invoice_for_processing(conn, invoice_id)
    catalogs = conn.execute(
        """
        SELECT p.id AS proveedor_id, c.id AS categoria_id,
               sc.id AS subcategoria_id
        FROM catalog.categorias c
        LEFT JOIN catalog.subcategorias sc ON sc.categoria_id = c.id AND sc.clave = %s
        LEFT JOIN catalog.proveedores p
          ON lower(p.nombre_normalizado) = lower(%s) AND p.activo
        WHERE c.clave = %s AND c.activa
        LIMIT 1
        """,
        (data.subcategoria_clave, data.proveedor, data.categoria_clave),
    ).fetchone()
    if not catalogs:
        raise DomainError("La categoría no existe o no está activa.", 422)

    if catalogs["proveedor_id"] is None:
        catalogs["proveedor_id"] = conn.execute(
            """
            INSERT INTO catalog.proveedores (rfc, nombre_legal, nombre_normalizado)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (data.rfc_emisor, data.proveedor, data.proveedor),
        ).fetchone()["id"]

    conn.execute("UPDATE core.facturas SET estado = 'ocr_procesando' WHERE id = %s", (invoice_id,))
    ocr_version = conn.execute(
        "SELECT COALESCE(max(version), 0) + 1 AS version FROM ocr.resultados WHERE factura_id = %s",
        (invoice_id,),
    ).fetchone()["version"]
    raw = data.model_dump(mode="json")
    ocr_id = conn.execute(
        """
        INSERT INTO ocr.resultados (
            factura_id, version, proveedor_ocr, modelo_ocr, texto_raw, json_raw, confianza
        ) VALUES (%s, %s, 'simulado', 'demo-v0.1', %s, %s::jsonb, %s)
        RETURNING id
        """,
        (invoice_id, ocr_version, json.dumps(raw), json.dumps(raw), data.confianza_ocr),
    ).fetchone()["id"]
    save_classification(
        conn,
        invoice_id,
        classify_document("FACTURA CFDI UUID SUBTOTAL IVA TIPO DE COMPROBANTE INGRESO"),
    )
    conn.execute("UPDATE core.facturas SET estado = 'ocr_completado' WHERE id = %s", (invoice_id,))
    conn.execute("UPDATE core.facturas SET estado = 'ia_procesando' WHERE id = %s", (invoice_id,))

    ia_version = conn.execute(
        "SELECT COALESCE(max(version), 0) + 1 AS version FROM ai.interpretaciones WHERE factura_id = %s",
        (invoice_id,),
    ).fetchone()["version"]
    interpretation_id = conn.execute(
        """
        INSERT INTO ai.interpretaciones (
            factura_id, ocr_resultado_id, version, modelo_ia, reglas_version,
            proveedor_id, proveedor_propuesto, rfc_emisor, uuid_fiscal,
            folio, folio_origen, fecha_emision, subtotal, descuento, iva, otros_impuestos, total,
            categoria_id, subcategoria_id, confianza, salida_json
        ) VALUES (
            %s, %s, %s, 'simulado', '0.1', %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        ) RETURNING id
        """,
        (
            invoice_id, ocr_id, ia_version, catalogs["proveedor_id"], data.proveedor,
            data.rfc_emisor, data.uuid_fiscal,
            (data.folio or data.fecha_emision.strftime("%d%m%Y")),
            ("detectado" if data.folio else "fecha"), data.fecha_emision, data.subtotal,
            data.descuento, data.iva, data.otros_impuestos, data.total,
            catalogs["categoria_id"], catalogs["subcategoria_id"],
            data.confianza_ia, json.dumps(raw),
        ),
    ).fetchone()["id"]
    conn.execute("UPDATE core.facturas SET estado = 'validando' WHERE id = %s", (invoice_id,))

    expected_total = data.subtotal - data.descuento + data.iva + data.otros_impuestos
    total_ok = abs(expected_total - data.total) <= Decimal("0.02")
    validations = [
        ("CUADRE_TOTAL", "error", total_ok, "total", "Los importes cuadran" if total_ok else "Los importes no cuadran"),
        ("PROVEEDOR", "error", catalogs["proveedor_id"] is not None, "proveedor", "Proveedor identificado"),
        ("REVISION_PILOTO", "informativa", False, None, "La v0.1 requiere revisión humana"),
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.validaciones
                (factura_id, interpretacion_id, codigo, severidad, aprobada, campo, mensaje)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [(invoice_id, interpretation_id, *validation) for validation in validations],
        )
    failed = sum(1 for _, severity, passed, _, _ in validations if not passed and severity == "error")
    conn.execute(
        "UPDATE core.facturas SET estado = 'requiere_revision', actualizada_en = now() WHERE id = %s",
        (invoice_id,),
    )
    return {
        "factura_id": invoice_id,
        "estado": "requiere_revision",
        "interpretacion_id": interpretation_id,
        "requiere_revision": True,
        "validaciones_fallidas": failed,
    }


def list_review_queue(
    conn: Connection,
    limit: int,
    offset: int,
    *,
    document_type: str | None = None,
    provider: str | None = None,
    branch_key: str | None = None,
    order: str = "prioridad",
) -> list[dict[str, Any]]:
    clauses = [
        "f.estado = 'requiere_revision'",
        "NOT EXISTS (SELECT 1 FROM core.documentos_duplicados dd WHERE dd.factura_duplicada_id = f.id AND dd.estado = 'pendiente')",
    ]
    params: list[Any] = []
    if document_type == "gastos":
        clauses.append("cd.tipo = ANY(%s::core.tipo_documento[])")
        params.append(["factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo"])
    elif document_type == "no_contabilizables":
        clauses.append("COALESCE(cd.tipo::text, 'desconocido') <> ALL(%s::text[])")
        params.append(["factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo"])
    elif document_type:
        clauses.append("cd.tipo::text = %s")
        params.append(document_type)
    if provider:
        clauses.append("COALESCE(p.nombre_normalizado, i.proveedor_propuesto, '') ILIKE %s")
        params.append(f"%{provider.strip()}%")
    if branch_key:
        clauses.append("s.clave = %s")
        params.append(branch_key)

    order_by = {
        "prioridad": "validaciones_fallidas DESC, f.recibida_en ASC",
        "recientes": "f.recibida_en DESC",
        "antiguas": "f.recibida_en ASC",
        "proveedor_az": "COALESCE(p.nombre_normalizado, i.proveedor_propuesto, '') ASC, f.recibida_en ASC",
        "proveedor_za": "COALESCE(p.nombre_normalizado, i.proveedor_propuesto, '') DESC, f.recibida_en ASC",
        "total_mayor": "i.total DESC NULLS LAST, f.recibida_en ASC",
        "total_menor": "i.total ASC NULLS LAST, f.recibida_en ASC",
    }.get(order)
    if order_by is None:
        raise DomainError("Orden de bandeja no reconocido.", 422)

    params.extend((limit, offset))
    return conn.execute(
        REVIEW_SELECT
        + f"""
        WHERE {' AND '.join(clauses)}
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
        """,
        params,
    ).fetchall()


def get_review_queue_summary(
    conn: Connection,
    *,
    document_type: str | None = None,
    provider: str | None = None,
    branch_key: str | None = None,
) -> dict[str, int]:
    clauses = [
        "f.estado = 'requiere_revision'",
        "NOT EXISTS (SELECT 1 FROM core.documentos_duplicados dd WHERE dd.factura_duplicada_id = f.id AND dd.estado = 'pendiente')",
    ]
    params: list[Any] = []
    if document_type == "gastos":
        clauses.append("cd.tipo = ANY(%s::core.tipo_documento[])")
        params.append(["factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo"])
    elif document_type == "no_contabilizables":
        clauses.append("COALESCE(cd.tipo::text, 'desconocido') <> ALL(%s::text[])")
        params.append(["factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo"])
    elif document_type:
        clauses.append("cd.tipo::text = %s")
        params.append(document_type)
    if provider:
        clauses.append("COALESCE(p.nombre_normalizado, i.proveedor_propuesto, '') ILIKE %s")
        params.append(f"%{provider.strip()}%")
    if branch_key:
        clauses.append("s.clave = %s")
        params.append(branch_key)

    row = conn.execute(
        """
        SELECT
            count(*)::integer AS total,
            count(*) FILTER (WHERE cd.tipo = 'factura_fiscal')::integer AS facturas,
            count(*) FILTER (WHERE cd.tipo = 'comprobante_pago')::integer AS pagos
        FROM core.facturas f
        JOIN catalog.sucursales s ON s.id = f.sucursal_id
        LEFT JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix
            WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id
        LEFT JOIN LATERAL (
            SELECT tipo FROM core.clasificaciones_documentales cdx
            WHERE cdx.factura_id = f.id ORDER BY cdx.version DESC LIMIT 1
        ) cd ON true
        WHERE """
        + " AND ".join(clauses),
        params,
    ).fetchone()
    total = row["total"]
    return {
        "total": total,
        "facturas": row["facturas"],
        "pagos": row["pagos"],
        "otros": total - row["facturas"] - row["pagos"],
    }


def get_invoice(conn: Connection, invoice_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        REVIEW_SELECT
        + """
        WHERE f.id = %s
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise DomainError("Factura no encontrada.", 404)
    return row


def get_invoice_case(conn: Connection, invoice_id: UUID) -> dict[str, Any]:
    invoice = conn.execute(
        """
        SELECT
            f.id, f.estado::text, f.recibida_en, f.archivo_nombre, f.archivo_mime,
            f.sucursal_origen, f.sucursal_deteccion,
            s.id AS sucursal_id, s.clave AS sucursal_clave, s.nombre AS sucursal,
            s.restaurante, i.id AS interpretacion_id, ff.id AS factura_final_id,
            CASE WHEN ff.id IS NOT NULL THEN ff.proveedor_id ELSE i.proveedor_id END AS proveedor_id,
            COALESCE(p.nombre_normalizado, i.proveedor_propuesto) AS proveedor,
            CASE WHEN ff.id IS NOT NULL THEN ff.rfc_emisor ELSE i.rfc_emisor END AS rfc_emisor,
            CASE WHEN ff.id IS NOT NULL THEN ff.uuid_fiscal ELSE i.uuid_fiscal END AS uuid_fiscal,
            CASE WHEN ff.id IS NOT NULL THEN ff.folio ELSE i.folio END AS folio,
            CASE WHEN ff.id IS NOT NULL THEN ff.folio_origen ELSE i.folio_origen END AS folio_origen,
            CASE WHEN ff.id IS NOT NULL THEN ff.fecha_emision ELSE i.fecha_emision END AS fecha_emision,
            CASE WHEN ff.id IS NOT NULL THEN ff.subtotal ELSE i.subtotal END AS subtotal,
            CASE WHEN ff.id IS NOT NULL THEN ff.descuento ELSE i.descuento END AS descuento,
            CASE WHEN ff.id IS NOT NULL THEN ff.iva ELSE i.iva END AS iva,
            CASE WHEN ff.id IS NOT NULL THEN ff.otros_impuestos ELSE i.otros_impuestos END AS otros_impuestos,
            CASE WHEN ff.id IS NOT NULL THEN ff.total ELSE i.total END AS total,
            CASE WHEN ff.id IS NOT NULL THEN ff.categoria_id ELSE i.categoria_id END AS categoria_id,
            c.nombre AS categoria,
            CASE WHEN ff.id IS NOT NULL THEN ff.subcategoria_id ELSE i.subcategoria_id END AS subcategoria_id,
            sc.nombre AS subcategoria,
            i.confianza,
            CASE WHEN ff.id IS NOT NULL THEN ff.observaciones ELSE i.observaciones END AS observaciones,
            i.proveedor_propuesto, i.salida_json,
            COALESCE(ff.genera_gasto, true) AS genera_gasto,
            COALESCE(ff.tipo_documento::text, cd.tipo::text) AS tipo_documento,
            cd.confianza AS confianza_clasificacion,
            cd.evidencia AS evidencia_clasificacion,
            CASE WHEN pg.id IS NULL THEN NULL ELSE jsonb_build_object(
                'tipo', pg.tipo,
                'periodo_desde', pg.periodo_desde,
                'periodo_hasta', pg.periodo_hasta
            ) END AS periodificacion
        FROM core.facturas f
        JOIN catalog.sucursales s ON s.id = f.sucursal_id
        LEFT JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix
            WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        LEFT JOIN LATERAL (
            SELECT * FROM core.facturas_finales ffx
            WHERE ffx.factura_id = f.id AND ffx.vigente
            ORDER BY ffx.version DESC LIMIT 1
        ) ff ON true
        LEFT JOIN catalog.proveedores p ON p.id = CASE WHEN ff.id IS NOT NULL THEN ff.proveedor_id ELSE i.proveedor_id END
        LEFT JOIN catalog.categorias c ON c.id = CASE WHEN ff.id IS NOT NULL THEN ff.categoria_id ELSE i.categoria_id END
        LEFT JOIN catalog.subcategorias sc ON sc.id = CASE WHEN ff.id IS NOT NULL THEN ff.subcategoria_id ELSE i.subcategoria_id END
        LEFT JOIN LATERAL (
            SELECT tipo, confianza, evidencia
            FROM core.clasificaciones_documentales cdx
            WHERE cdx.factura_id = f.id ORDER BY cdx.version DESC LIMIT 1
        ) cd ON true
        LEFT JOIN finance.periodificaciones_gasto pg ON pg.factura_id = f.id
        WHERE f.id = %s
        """,
        (invoice_id,),
    ).fetchone()
    if not invoice:
        raise DomainError("Factura no encontrada.", 404)

    validations = []
    if invoice["interpretacion_id"]:
        validations = conn.execute(
            """
            SELECT codigo, severidad::text, aprobada, campo, mensaje, esperado, observado
            FROM core.validaciones WHERE interpretacion_id = %s
            ORDER BY CASE severidad WHEN 'error' THEN 1 WHEN 'advertencia' THEN 2 ELSE 3 END, codigo
            """,
            (invoice["interpretacion_id"],),
        ).fetchall()
    return {"factura": invoice, "validaciones": validations}


def list_catalogs(conn: Connection) -> dict[str, list[dict[str, Any]]]:
    return {
        "sucursales": conn.execute(
            """
            SELECT id, clave, nombre, restaurante, razon_social, rfc, aliases
            FROM catalog.sucursales WHERE activa ORDER BY restaurante, nombre
            """
        ).fetchall(),
        "proveedores": conn.execute(
            """
            SELECT id, nombre_normalizado AS nombre, rfc, es_informal, telefono, giro
            FROM catalog.proveedores WHERE activo ORDER BY nombre_normalizado
            """
        ).fetchall(),
        "categorias": conn.execute(
            "SELECT id, clave, nombre, tipo_costo, admite_facturas FROM catalog.categorias WHERE activa AND admite_facturas ORDER BY orden, nombre"
        ).fetchall(),
        "subcategorias": conn.execute(
            "SELECT id, categoria_id, clave, nombre FROM catalog.subcategorias WHERE activa ORDER BY nombre"
        ).fetchall(),
        "reglas_periodificacion": conn.execute(
            """
            SELECT proveedor_id, subcategoria_id, tipo
            FROM catalog.reglas_periodificacion WHERE activa
            ORDER BY actualizada_en DESC
            """
        ).fetchall(),
    }


def search_documents(conn: Connection, number: str, limit: int = 50) -> list[dict[str, Any]]:
    term = number.strip()
    if not term:
        raise DomainError("Escribe un número de factura, nota, ticket o una fecha DDMMYYYY.", 422)
    return conn.execute(
        """
        WITH documentos AS (
            SELECT f.id, 'documento_cargado'::text AS origen,
                   COALESCE(NULLIF(i.folio, ''), to_char(i.fecha_emision, 'DDMMYYYY')) AS numero_documento,
                   i.folio_origen AS numero_origen, f.archivo_nombre,
                   f.estado::text AS estado, i.fecha_emision AS fecha,
                   COALESCE(p.nombre_normalizado, i.proveedor_propuesto) AS proveedor,
                   s.nombre AS sucursal, s.restaurante,
                   '/api/v1/facturas/' || f.id::text || '/archivo' AS archivo_url
            FROM core.facturas f
            JOIN catalog.sucursales s ON s.id = f.sucursal_id
            LEFT JOIN LATERAL (
                SELECT * FROM ai.interpretaciones ix
                WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
            ) i ON true
            LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id

            UNION ALL

            SELECT ci.id, 'comprobante_interno'::text, ci.numero_documento,
                   ci.numero_documento_origen, ci.folio || '.pdf', ci.estado,
                   ci.fecha_gasto, p.nombre_normalizado, s.nombre, s.restaurante,
                   '/api/v1/comprobantes-internos/' || ci.id::text || '/pdf'
            FROM core.comprobantes_internos ci
            JOIN catalog.sucursales s ON s.id = ci.sucursal_id
            JOIN catalog.proveedores p ON p.id = ci.proveedor_id
        )
        SELECT * FROM documentos
        WHERE lower(numero_documento) LIKE lower(%s)
        ORDER BY (lower(numero_documento) = lower(%s)) DESC, fecha DESC NULLS LAST
        LIMIT %s
        """,
        (f"%{term}%", term, limit),
    ).fetchall()


def browse_documents(
    conn: Connection,
    *,
    query: str | None = None,
    estado: str = "aprobada",
    sucursal_clave: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    term = (query or "").strip()
    pattern = f"%{term}%"
    return conn.execute(
        """
        WITH documentos AS (
            SELECT f.id, 'documento_cargado'::text AS origen,
                   COALESCE(NULLIF(i.folio, ''), to_char(i.fecha_emision, 'DDMMYYYY')) AS numero_documento,
                   i.folio_origen AS numero_origen, f.archivo_nombre,
                   f.estado::text AS estado, i.fecha_emision AS fecha,
                   COALESCE(p.nombre_normalizado, i.proveedor_propuesto) AS proveedor,
                   s.clave AS sucursal_clave, s.nombre AS sucursal, s.restaurante,
                   COALESCE(i.total, 0)::numeric(14,2) AS total,
                   COALESCE(ff.tipo_documento::text, cd.tipo::text, 'desconocido') AS tipo_documento,
                   COALESCE(ff.aprobada_en, f.actualizada_en) AS actividad_en,
                   '/api/v1/facturas/' || f.id::text || '/archivo' AS archivo_url
            FROM core.facturas f
            JOIN catalog.sucursales s ON s.id = f.sucursal_id
            LEFT JOIN LATERAL (
                SELECT * FROM ai.interpretaciones ix
                WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
            ) i ON true
            LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id
            LEFT JOIN core.facturas_finales ff ON ff.factura_id = f.id
            LEFT JOIN LATERAL (
                SELECT tipo FROM core.clasificaciones_documentales cx
                WHERE cx.factura_id = f.id ORDER BY cx.version DESC LIMIT 1
            ) cd ON true

            UNION ALL

            SELECT ci.id, 'comprobante_interno'::text, ci.numero_documento,
                   ci.numero_documento_origen, ci.folio || '.pdf', ci.estado,
                   ci.fecha_gasto, p.nombre_normalizado, s.clave, s.nombre, s.restaurante,
                   ci.total, 'comprobante_interno'::text,
                   COALESCE(ci.primera_aprobacion_en, ci.actualizado_en),
                   '/api/v1/comprobantes-internos/' || ci.id::text || '/pdf'
            FROM core.comprobantes_internos ci
            JOIN catalog.sucursales s ON s.id = ci.sucursal_id
            JOIN catalog.proveedores p ON p.id = ci.proveedor_id
        )
        SELECT * FROM documentos
        WHERE (%s = '' OR lower(concat_ws(' ', numero_documento, numero_origen, proveedor, archivo_nombre)) LIKE lower(%s))
          AND (%s = 'todos' OR estado = %s
               OR (%s = 'aprobada' AND estado = 'aprobado')
               OR (%s = 'rechazada' AND estado = 'rechazado')
               OR (%s = 'requiere_revision' AND estado IN ('pendiente_aprobacion', 'pendiente_segunda_aprobacion')))
          AND (%s::text IS NULL OR sucursal_clave = %s)
          AND (%s::date IS NULL OR fecha >= %s)
          AND (%s::date IS NULL OR fecha <= %s)
        ORDER BY actividad_en DESC NULLS LAST, fecha DESC NULLS LAST
        LIMIT %s
        """,
        (
            term, pattern,
            estado, estado, estado, estado, estado,
            sucursal_clave, sucursal_clave,
            fecha_desde, fecha_desde,
            fecha_hasta, fecha_hasta,
            limit,
        ),
    ).fetchall()


def get_analytics_summary(conn: Connection) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT count(DISTINCT movimiento_id)::integer AS facturas_aprobadas,
               COALESCE(sum(total), 0)::numeric(14,2) AS total_aprobado,
               max(aprobada_en) AS ultima_aprobacion
        FROM analytics.movimientos_gasto
        """
    ).fetchone()
    weekly = conn.execute(
        """
        SELECT anio_iso, semana_iso, count(DISTINCT movimiento_id)::integer AS facturas,
               COALESCE(sum(total), 0)::numeric(14,2) AS total
        FROM analytics.movimientos_gasto
        GROUP BY anio_iso, semana_iso
        ORDER BY anio_iso DESC, semana_iso DESC
        LIMIT 1
        """
    ).fetchone()
    return {**totals, "semana_actual": weekly}


def _aggregate_analytics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    amount_rows = [row for row in rows if row["total"] is not None]
    total = sum((row["total"] for row in amount_rows), Decimal("0"))
    movement_ids = {row.get("movimiento_id") or id(row) for row in rows}
    movements_with_total = {row.get("movimiento_id") or id(row) for row in amount_rows}

    def grouped(field: str, empty_label: str) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            label = row.get(field) or empty_label
            item = groups.setdefault(
                label, {"nombre": label, "facturas": 0, "total": Decimal("0"), "_ids": set()}
            )
            movement_id = row.get("movimiento_id") or id(row)
            item["_ids"].add(movement_id)
            item["facturas"] = len(item["_ids"])
            item["total"] += row.get("total") or Decimal("0")
        result = []
        for item in groups.values():
            item.pop("_ids", None)
            result.append(item)
        return sorted(result, key=lambda item: (item["total"], item["facturas"]), reverse=True)

    daily: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("fecha") is None:
            continue
        day = row["fecha"].isoformat()
        item = daily.setdefault(
            day, {"fecha": day, "facturas": 0, "total": Decimal("0"), "_ids": set()}
        )
        item["_ids"].add(row.get("movimiento_id") or id(row))
        item["facturas"] = len(item["_ids"])
        item["total"] += row.get("total") or Decimal("0")

    recent = sorted(
        rows,
        key=lambda row: (row.get("fecha") is not None, row.get("fecha")),
        reverse=True,
    )[:10]
    return {
        "facturas": len(movement_ids),
        "facturas_con_total": len(movements_with_total),
        "total": total,
        "ticket_promedio": total / len(movements_with_total) if movements_with_total else Decimal("0"),
        "categorias": grouped("categoria", "Sin categoría"),
        "proveedores": grouped("proveedor", "Proveedor sin identificar")[:8],
        "restaurantes": grouped("restaurante", "Por asignar"),
        "tendencia_diaria": [
            {key: value for key, value in daily[day].items() if key != "_ids"}
            for day in sorted(daily)
        ],
        "recientes": recent,
    }


def _filter_analytics_rows(
    rows: list[dict[str, Any]],
    *,
    anio_iso: int | None = None,
    semana_iso: int | None = None,
    fecha_desde=None,
    fecha_hasta=None,
    categoria: str | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    for row in rows:
        row_date = row.get("fecha")
        if anio_iso is not None and semana_iso is not None:
            if row_date is None:
                continue
            iso = row_date.isocalendar()
            if iso.year != anio_iso or iso.week != semana_iso:
                continue
        if fecha_desde is not None and (row_date is None or row_date < fecha_desde):
            continue
        if fecha_hasta is not None and (row_date is None or row_date > fecha_hasta):
            continue
        if categoria and str(row.get("categoria") or "").upper() != categoria.upper():
            continue
        filtered.append(row)
    return filtered


def get_analytics_dashboard(
    conn: Connection,
    *,
    anio_iso: int | None = None,
    semana_iso: int | None = None,
    fecha_desde=None,
    fecha_hasta=None,
    categoria: str | None = None,
) -> dict[str, Any]:
    approved = conn.execute(
        """
        SELECT movimiento_id, documento_origen_id, tipo_documento, folio, fecha, restaurante, sucursal,
               proveedor, categoria, subcategoria, total, estado_fiscal,
               'aprobada'::text AS estado
        FROM analytics.movimientos_gasto
        ORDER BY fecha DESC, aprobada_en DESC
        """
    ).fetchall()
    pending = conn.execute(
        """
        SELECT f.id AS movimiento_id, f.id AS documento_origen_id, cd.tipo::text AS tipo_documento,
               NULL::text AS folio, i.fecha_emision AS fecha, s.restaurante, s.nombre AS sucursal,
               COALESCE(p.nombre_normalizado, i.proveedor_propuesto) AS proveedor,
               c.nombre AS categoria, sc.nombre AS subcategoria, i.total,
               CASE WHEN cd.tipo = 'factura_fiscal' THEN 'pendiente_cfdi'
                    ELSE 'no_deducible' END AS estado_fiscal,
               'requiere_revision'::text AS estado
        FROM core.facturas f
        JOIN catalog.sucursales s ON s.id = f.sucursal_id
        JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix
            WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id
        LEFT JOIN catalog.categorias c ON c.id = i.categoria_id
        LEFT JOIN catalog.subcategorias sc ON sc.id = i.subcategoria_id
        JOIN LATERAL (
            SELECT tipo FROM core.clasificaciones_documentales cdx
            WHERE cdx.factura_id = f.id ORDER BY cdx.version DESC LIMIT 1
        ) cd ON true
        WHERE f.estado = 'requiere_revision'
          AND NOT EXISTS (
              SELECT 1 FROM core.documentos_duplicados dd
              WHERE dd.factura_duplicada_id = f.id AND dd.estado = 'pendiente'
          )
          AND cd.tipo IN ('factura_fiscal', 'ticket_compra', 'nota_venta', 'remision', 'recibo')
        ORDER BY i.fecha_emision DESC NULLS LAST, f.recibida_en DESC
        """
    ).fetchall()
    pending_receipts = conn.execute(
        """
        SELECT ci.id AS movimiento_id, ci.id AS documento_origen_id, 'comprobante_interno'::text AS tipo_documento,
               ci.folio, ci.fecha_gasto AS fecha, s.restaurante, s.nombre AS sucursal,
               p.nombre_normalizado AS proveedor, c.nombre AS categoria,
               sc.nombre AS subcategoria, ci.total, ci.estado_fiscal,
               ci.estado
        FROM core.comprobantes_internos ci
        JOIN catalog.sucursales s ON s.id = ci.sucursal_id
        JOIN catalog.proveedores p ON p.id = ci.proveedor_id
        JOIN catalog.categorias c ON c.id = ci.categoria_id
        LEFT JOIN catalog.subcategorias sc ON sc.id = ci.subcategoria_id
        WHERE ci.estado = 'pendiente_aprobacion'
        ORDER BY ci.fecha_gasto DESC, ci.creado_en DESC
        """
    ).fetchall()
    filter_options = {
        "anio_iso": anio_iso,
        "semana_iso": semana_iso,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "categoria": categoria,
    }
    approved = _filter_analytics_rows(approved, **filter_options)
    all_pending = _filter_analytics_rows([*pending, *pending_receipts], **filter_options)
    pending_total = sum((row["total"] or Decimal("0") for row in all_pending), Decimal("0"))
    return {
        "aprobado": _aggregate_analytics(approved),
        "preliminar": _aggregate_analytics([*approved, *all_pending]),
        "pendiente": {"facturas": len(all_pending), "total": pending_total},
        "filtros": {
            "anio_iso": anio_iso,
            "semana_iso": semana_iso,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "categoria": categoria,
        },
    }


def get_analytics_export_rows(
    conn: Connection,
    *,
    anio_iso: int | None = None,
    semana_iso: int | None = None,
    fecha_desde=None,
    fecha_hasta=None,
    categoria: str | None = None,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tipo_documento, folio, fecha, anio_iso, semana_iso, restaurante, sucursal, proveedor,
               proveedor_rfc, categoria, subcategoria, moneda,
               subtotal, descuento, iva, otros_impuestos, total, estado_fiscal
        FROM analytics.movimientos_gasto
        ORDER BY fecha, proveedor, total
        """
    ).fetchall()
    return _filter_analytics_rows(
        rows,
        anio_iso=anio_iso,
        semana_iso=semana_iso,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        categoria=categoria,
    )


def _invoice_category(conn: Connection, category_id: UUID) -> dict[str, Any]:
    category = conn.execute(
        "SELECT clave, nombre, admite_facturas FROM catalog.categorias WHERE id = %s AND activa",
        (category_id,),
    ).fetchone()
    if not category:
        raise DomainError("La categoría elegida no está activa.", 422)
    if not category["admite_facturas"]:
        raise DomainError(
            f"La categoría {category['nombre']} no se captura con facturas; se registra por separado.", 422
        )
    return category


def _review_context(conn: Connection, invoice_id: UUID) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT f.id AS factura_id, f.estado::text, f.sucursal_id,
               i.*, p.id AS resolved_proveedor_id,
               p.nombre_normalizado AS proveedor_nombre,
               cd.tipo::text AS tipo_documento
        FROM core.facturas f
        JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix
            WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        LEFT JOIN catalog.proveedores p ON p.id = i.proveedor_id
        LEFT JOIN LATERAL (
            SELECT tipo FROM core.clasificaciones_documentales cdx
            WHERE cdx.factura_id = f.id ORDER BY cdx.version DESC LIMIT 1
        ) cd ON true
        WHERE f.id = %s FOR UPDATE OF f
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise DomainError("Factura no encontrada o sin interpretación.", 404)
    if row["estado"] != "requiere_revision":
        raise DomainError(f"La factura no está pendiente de revisión: {row['estado']}.", 409)
    return row


FINAL_FIELDS = {
    "proveedor_id", "proveedor_nombre", "sucursal_id", "folio", "folio_origen", "fecha_emision", "subtotal", "descuento", "iva",
    "otros_impuestos", "total", "categoria_id", "subcategoria_id",
    "rfc_emisor", "uuid_fiscal", "observaciones",
}


def decide_invoice(
    conn: Connection,
    invoice_id: UUID,
    *,
    actor: str,
    decision: str,
    comment: str | None,
    corrections: list[dict[str, Any]] | None = None,
    force_as_expense: bool = False,
    remember_alias: bool = False,
    remember_classification: bool = False,
    periodification: dict[str, Any] | None = None,
    remember_periodification: bool = False,
) -> dict[str, Any]:
    context = _review_context(conn, invoice_id)
    review_comment = comment
    recognized_expense = is_expense_document(context["tipo_documento"])
    if force_as_expense and not recognized_expense and not review_comment:
        review_comment = "Clasificación corregida manualmente: el documento sí genera gasto."
    review_id = conn.execute(
        """
        INSERT INTO core.revisiones
            (factura_id, interpretacion_id, decision, revisada_por, comentario)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (invoice_id, context["id"], decision, actor, review_comment),
    ).fetchone()["id"]

    if decision == "rechazada":
        conn.execute(
            "UPDATE core.facturas SET estado = 'rechazada', actualizada_en = now() WHERE id = %s",
            (invoice_id,),
        )
        return {"factura_id": invoice_id, "estado": "rechazada", "factura_final_id": None}

    if not recognized_expense and not force_as_expense:
        raise DomainError(
            "Este tipo de documento no se reconoce como comprobante de gasto. "
            "Marque la confirmación manual si el documento sí genera gasto.",
            422,
        )

    final_document_type = context["tipo_documento"]
    if not recognized_expense and force_as_expense:
        final_document_type = "recibo"
        version = conn.execute(
            """
            SELECT COALESCE(max(version), 0) + 1 AS version
            FROM core.clasificaciones_documentales WHERE factura_id = %s
            """,
            (invoice_id,),
        ).fetchone()["version"]
        evidence = {
            "override_manual": True,
            "tipo_anterior": context["tipo_documento"],
            "revisada_por": actor,
            "revision_id": str(review_id),
        }
        conn.execute(
            """
            INSERT INTO core.clasificaciones_documentales (
                factura_id, version, tipo, confianza, clasificador,
                reglas_version, evidencia
            ) VALUES (%s, %s, 'recibo', 1, 'revision_humana', 'manual-v2', %s::jsonb)
            """,
            (invoice_id, version, json.dumps(evidence)),
        )

    values = {field: context.get(field) for field in FINAL_FIELDS}
    provider_name_changed = False
    folio_changed = False
    date_changed = False
    for correction in corrections or []:
        field = correction["campo"]
        old_value = values.get(field)
        values[field] = correction["valor"]
        provider_name_changed = provider_name_changed or field == "proveedor_nombre"
        folio_changed = folio_changed or field == "folio"
        date_changed = date_changed or field == "fecha_emision"
        conn.execute(
            """
            INSERT INTO audit.correcciones (
                revision_id, factura_id, campo, valor_propuesto,
                valor_corregido, motivo, corregido_por
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                review_id, invoice_id, field, json.dumps(old_value, default=str),
                json.dumps(values[field], default=str), correction.get("motivo"), actor,
            ),
        )

    if folio_changed:
        values["folio_origen"] = "manual"
    elif date_changed and values.get("folio_origen") == "fecha" and values.get("fecha_emision"):
        parsed_date = values["fecha_emision"]
        if isinstance(parsed_date, str):
            from datetime import date
            parsed_date = date.fromisoformat(parsed_date)
        values["folio"] = parsed_date.strftime("%d%m%Y")
    if not str(values.get("folio") or "").strip() and values.get("fecha_emision"):
        parsed_date = values["fecha_emision"]
        if isinstance(parsed_date, str):
            from datetime import date
            parsed_date = date.fromisoformat(parsed_date)
        values["folio"] = parsed_date.strftime("%d%m%Y")
        values["folio_origen"] = "fecha"

    if provider_name_changed:
        provider_name = str(values.get("proveedor_nombre") or "").strip()
        if not provider_name:
            raise DomainError("El nombre del proveedor no puede quedar vacío.", 422)
        provider = conn.execute(
            """
            SELECT id FROM catalog.proveedores
            WHERE lower(nombre_normalizado) = lower(%s) AND activo
            LIMIT 1
            """,
            (provider_name,),
        ).fetchone()
        if provider is None and values.get("rfc_emisor"):
            provider = conn.execute(
                """
                UPDATE catalog.proveedores
                SET nombre_legal = %s, nombre_normalizado = %s, activo = true
                WHERE rfc = %s
                RETURNING id
                """,
                (provider_name, provider_name, values["rfc_emisor"]),
            ).fetchone()
        if provider is None:
            provider = conn.execute(
                """
                INSERT INTO catalog.proveedores (rfc, nombre_legal, nombre_normalizado)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (values.get("rfc_emisor"), provider_name, provider_name),
            ).fetchone()
        values["proveedor_id"] = provider["id"]

    required = ("proveedor_id", "sucursal_id", "fecha_emision", "total", "categoria_id")
    missing = [field for field in required if values.get(field) in (None, "")]
    if missing:
        raise DomainError(f"Faltan campos obligatorios para aprobar: {', '.join(missing)}.", 422)
    branch = conn.execute(
        "SELECT clave FROM catalog.sucursales WHERE id = %s AND activa",
        (values["sucursal_id"],),
    ).fetchone()
    if not branch:
        raise DomainError("La sucursal elegida no está activa.", 422)
    if branch["clave"] == "POR-ASIGNAR":
        raise DomainError(
            "Asigne una sucursal real antes de aprobar y publicar el gasto.", 422
        )
    category = _invoice_category(conn, values["categoria_id"])

    if remember_alias:
        output = context.get("salida_json") or {}
        alias_source = (
            output.get("proveedor_ocr_original")
            or output.get("proveedor_propuesto")
            or context.get("proveedor_propuesto")
        )
        if alias_source:
            previous_provider_id = context.get("proveedor_id")
            if previous_provider_id and previous_provider_id != values["proveedor_id"]:
                previous = conn.execute(
                    "SELECT nombre_normalizado FROM catalog.proveedores WHERE id = %s AND activo",
                    (previous_provider_id,),
                ).fetchone()
                already_published = conn.execute(
                    "SELECT 1 FROM core.facturas_finales WHERE proveedor_id = %s LIMIT 1",
                    (previous_provider_id,),
                ).fetchone()
                if (
                    previous
                    and normalize_alias(previous["nombre_normalizado"]) == normalize_alias(str(alias_source))
                    and not already_published
                ):
                    conn.execute(
                        "UPDATE catalog.reglas_clasificacion SET activa = false WHERE proveedor_id = %s",
                        (previous_provider_id,),
                    )
                    conn.execute(
                        "UPDATE catalog.proveedores SET activo = false WHERE id = %s",
                        (previous_provider_id,),
                    )
            remember_provider_alias(
                conn,
                provider_id=values["proveedor_id"],
                alias=str(alias_source),
                actor=actor,
                invoice_id=invoice_id,
                review_id=review_id,
            )
    if remember_classification:
        remember_accounting_rule(
            conn,
            provider_id=values["proveedor_id"],
            category_id=values["categoria_id"],
            subcategory_id=values.get("subcategoria_id"),
            actor=actor,
            invoice_id=invoice_id,
            review_id=review_id,
        )

    if values.get("uuid_fiscal"):
        duplicate = conn.execute(
            """
            SELECT f.id, f.archivo_nombre, ff.folio, ff.total
            FROM core.facturas_finales ff
            JOIN core.facturas f ON f.id = ff.factura_id
            WHERE ff.uuid_fiscal = %s AND ff.vigente AND f.id <> %s
            LIMIT 1
            """,
            (values["uuid_fiscal"], invoice_id),
        ).fetchone()
        if duplicate:
            raise DomainError(
                f"Factura duplicada: el UUID ya fue aprobado desde {duplicate['archivo_nombre']} "
                f"(folio {duplicate['folio'] or 'sin folio'}, total {duplicate['total']}).",
                409,
            )

    final_id = conn.execute(
        """
        INSERT INTO core.facturas_finales (
            factura_id, revision_id, interpretacion_id, sucursal_id, proveedor_id,
            rfc_emisor, uuid_fiscal, folio, folio_origen, fecha_emision, subtotal, descuento, iva,
            otros_impuestos, total, categoria_id, subcategoria_id,
            observaciones, aprobada_por, tipo_documento, estado_fiscal
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s
        ) RETURNING id
        """,
        (
            invoice_id, review_id, context["id"], values["sucursal_id"],
            values["proveedor_id"], values.get("rfc_emisor"), values.get("uuid_fiscal"),
            values.get("folio"), values.get("folio_origen"), values["fecha_emision"],
            values.get("subtotal"), values.get("descuento"),
            values.get("iva"), values.get("otros_impuestos"), values["total"],
            values["categoria_id"], values.get("subcategoria_id"),
            values.get("observaciones"), actor,
            final_document_type,
            "con_cfdi" if final_document_type == "factura_fiscal" else "no_deducible",
        ),
    ).fetchone()["id"]
    save_periodification(
        conn,
        invoice_id=invoice_id,
        total=Decimal(values["total"]),
        category_key=category["clave"],
        provider_id=values["proveedor_id"],
        subcategory_id=values.get("subcategoria_id"),
        config=periodification,
        actor=actor,
        remember=remember_periodification,
    )
    conn.execute(
        """
        UPDATE core.facturas SET estado = 'aprobada', sucursal_id = %s,
            sucursal_origen = CASE WHEN sucursal_id IS DISTINCT FROM %s
                THEN 'revision_humana' ELSE sucursal_origen END,
            actualizada_en = now()
        WHERE id = %s
        """,
        (values["sucursal_id"], values["sucursal_id"], invoice_id),
    )
    conn.execute(
        """
        UPDATE audit.inferencias_sucursal
        SET sucursal_confirmada_id = %s, confirmada_por = %s, confirmada_en = now()
        WHERE id = (
            SELECT id FROM audit.inferencias_sucursal
            WHERE factura_id = %s ORDER BY creada_en DESC LIMIT 1
        )
        """,
        (values["sucursal_id"], actor, invoice_id),
    )
    return {"factura_id": invoice_id, "estado": "aprobada", "factura_final_id": final_id}


def edit_approved_invoice(
    conn: Connection,
    invoice_id: UUID,
    *,
    actor: str,
    comment: str | None,
    corrections: list[dict[str, Any]],
    generates_expense: bool | None = None,
    remember_alias: bool = False,
    remember_classification: bool = False,
    periodification: dict[str, Any] | None = None,
    remember_periodification: bool = False,
) -> dict[str, Any]:
    actor = actor.strip()
    if not actor:
        raise DomainError("Indique quién realiza la edición.", 422)
    if not corrections and periodification is None and generates_expense is None and not (
        remember_alias or remember_classification or remember_periodification
    ):
        raise DomainError("No hay cambios para guardar.", 422)

    context = conn.execute(
        """
        SELECT f.estado::text, ff.*, p.nombre_normalizado AS proveedor_nombre,
               i.salida_json, i.proveedor_propuesto
        FROM core.facturas f
        JOIN core.facturas_finales ff ON ff.factura_id = f.id AND ff.vigente
        JOIN catalog.proveedores p ON p.id = ff.proveedor_id
        JOIN ai.interpretaciones i ON i.id = ff.interpretacion_id
        WHERE f.id = %s
        FOR UPDATE OF f, ff
        """,
        (invoice_id,),
    ).fetchone()
    if not context:
        raise DomainError("La factura aprobada no fue encontrada.", 404)
    if context["estado"] != "aprobada":
        raise DomainError("Solo se utiliza esta edición después de aprobar la factura.", 409)

    values = {
        "proveedor_id": context["proveedor_id"],
        "proveedor_nombre": context["proveedor_nombre"],
        "sucursal_id": context["sucursal_id"],
        "folio": context["folio"],
        "folio_origen": context["folio_origen"],
        "fecha_emision": context["fecha_emision"],
        "subtotal": context["subtotal"],
        "descuento": context["descuento"],
        "iva": context["iva"],
        "otros_impuestos": context["otros_impuestos"],
        "total": context["total"],
        "categoria_id": context["categoria_id"],
        "subcategoria_id": context["subcategoria_id"],
        "rfc_emisor": context["rfc_emisor"],
        "uuid_fiscal": context["uuid_fiscal"],
        "observaciones": context["observaciones"],
    }
    provider_name_changed = False
    folio_changed = False
    date_changed = False
    changed_rows: list[tuple[str, Any, Any, str | None]] = []
    for correction in corrections:
        field = correction["campo"]
        if field not in FINAL_FIELDS:
            raise DomainError(f"El campo {field} no se puede editar.", 422)
        old_value = values.get(field)
        new_value = correction["valor"]
        values[field] = new_value
        provider_name_changed = provider_name_changed or field == "proveedor_nombre"
        folio_changed = folio_changed or field == "folio"
        date_changed = date_changed or field == "fecha_emision"
        changed_rows.append((field, old_value, new_value, correction.get("motivo")))
    if generates_expense is not None and generates_expense != context["genera_gasto"]:
        changed_rows.append((
            "genera_gasto", context["genera_gasto"], generates_expense,
            "Cambio manual del impacto financiero",
        ))

    if folio_changed:
        values["folio_origen"] = "manual"
    elif date_changed and values.get("folio_origen") == "fecha" and values.get("fecha_emision"):
        parsed_date = values["fecha_emision"]
        if isinstance(parsed_date, str):
            from datetime import date
            parsed_date = date.fromisoformat(parsed_date)
        values["folio"] = parsed_date.strftime("%d%m%Y")
    if not str(values.get("folio") or "").strip() and values.get("fecha_emision"):
        parsed_date = values["fecha_emision"]
        if isinstance(parsed_date, str):
            from datetime import date
            parsed_date = date.fromisoformat(parsed_date)
        values["folio"] = parsed_date.strftime("%d%m%Y")
        values["folio_origen"] = "fecha"

    if provider_name_changed:
        provider_name = str(values.get("proveedor_nombre") or "").strip()
        if not provider_name:
            raise DomainError("El nombre del proveedor no puede quedar vacío.", 422)
        provider = conn.execute(
            """
            SELECT id FROM catalog.proveedores
            WHERE lower(nombre_normalizado) = lower(%s) AND activo LIMIT 1
            """,
            (provider_name,),
        ).fetchone()
        if provider is None and values.get("rfc_emisor"):
            provider = conn.execute(
                """
                UPDATE catalog.proveedores
                SET nombre_legal = %s, nombre_normalizado = %s, activo = true
                WHERE rfc = %s RETURNING id
                """,
                (provider_name, provider_name, values["rfc_emisor"]),
            ).fetchone()
        if provider is None:
            provider = conn.execute(
                """
                INSERT INTO catalog.proveedores (rfc, nombre_legal, nombre_normalizado)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (values.get("rfc_emisor"), provider_name, provider_name),
            ).fetchone()
        values["proveedor_id"] = provider["id"]

    required = ("proveedor_id", "sucursal_id", "fecha_emision", "total", "categoria_id")
    missing = [field for field in required if values.get(field) in (None, "")]
    if missing:
        raise DomainError(f"Faltan campos obligatorios: {', '.join(missing)}.", 422)
    if Decimal(str(values["total"])) <= 0:
        raise DomainError("El total debe ser mayor a cero.", 422)
    branch = conn.execute(
        "SELECT clave FROM catalog.sucursales WHERE id = %s AND activa",
        (values["sucursal_id"],),
    ).fetchone()
    if not branch or branch["clave"] == "POR-ASIGNAR":
        raise DomainError("Seleccione una sucursal activa antes de guardar.", 422)
    category = _invoice_category(conn, values["categoria_id"])
    if values.get("subcategoria_id") and not conn.execute(
        "SELECT 1 FROM catalog.subcategorias WHERE id = %s AND categoria_id = %s AND activa",
        (values["subcategoria_id"], values["categoria_id"]),
    ).fetchone():
        raise DomainError("La subcategoría no corresponde a la categoría seleccionada.", 422)

    review_id = conn.execute(
        """
        INSERT INTO core.revisiones (
            factura_id, interpretacion_id, decision, revisada_por, comentario
        ) VALUES (%s, %s, 'corregida_y_aprobada', %s, %s) RETURNING id
        """,
        (
            invoice_id, context["interpretacion_id"], actor,
            comment or "Edición posterior a la aprobación",
        ),
    ).fetchone()["id"]
    for field, old_value, new_value, reason in changed_rows:
        conn.execute(
            """
            INSERT INTO audit.correcciones (
                revision_id, factura_id, campo, valor_propuesto,
                valor_corregido, motivo, corregido_por
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                review_id, invoice_id, field, json.dumps(old_value, default=str),
                json.dumps(new_value, default=str), reason or "Edición posterior", actor,
            ),
        )

    conn.execute(
        "UPDATE core.facturas_finales SET vigente = false WHERE id = %s",
        (context["id"],),
    )
    final_id = conn.execute(
        """
        INSERT INTO core.facturas_finales (
            factura_id, revision_id, interpretacion_id, version, vigente,
            sucursal_id, proveedor_id, rfc_emisor, uuid_fiscal, serie, folio,
            folio_origen, fecha_emision, moneda, metodo_pago, forma_pago,
            subtotal, descuento, iva, otros_impuestos, total,
            categoria_id, subcategoria_id, observaciones,
            aprobada_por, tipo_documento, estado_fiscal, genera_gasto
        ) VALUES (
            %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) RETURNING id
        """,
        (
            invoice_id, review_id, context["interpretacion_id"], context["version"] + 1,
            values["sucursal_id"], values["proveedor_id"], values.get("rfc_emisor"),
            values.get("uuid_fiscal"), context["serie"], values.get("folio"),
            values.get("folio_origen"), values["fecha_emision"], context["moneda"],
            context["metodo_pago"], context["forma_pago"], values.get("subtotal"),
            values.get("descuento"), values.get("iva"), values.get("otros_impuestos"),
            values["total"], values["categoria_id"], values.get("subcategoria_id"),
            values.get("observaciones"), actor,
            context["tipo_documento"], context["estado_fiscal"],
            context["genera_gasto"] if generates_expense is None else generates_expense,
        ),
    ).fetchone()["id"]

    existing_period = conn.execute(
        """
        SELECT tipo, periodo_desde, periodo_hasta
        FROM finance.periodificaciones_gasto WHERE factura_id = %s
        """,
        (invoice_id,),
    ).fetchone()
    effective_expense = context["genera_gasto"] if generates_expense is None else generates_expense
    if category["clave"] == "FIJOS" and effective_expense:
        config = periodification or (dict(existing_period) if existing_period else None)
        if config:
            save_periodification(
                conn,
                invoice_id=invoice_id,
                total=Decimal(str(values["total"])),
                category_key=category["clave"],
                provider_id=values["proveedor_id"],
                subcategory_id=values.get("subcategoria_id"),
                config=config,
                actor=actor,
                remember=remember_periodification,
            )
    elif existing_period:
        conn.execute(
            "DELETE FROM finance.periodificaciones_gasto WHERE factura_id = %s",
            (invoice_id,),
        )

    if remember_alias:
        output = context.get("salida_json") or {}
        alias_source = output.get("proveedor_ocr_original") or context.get("proveedor_propuesto")
        if alias_source:
            remember_provider_alias(
                conn,
                provider_id=values["proveedor_id"],
                alias=str(alias_source),
                actor=actor,
                invoice_id=invoice_id,
                review_id=review_id,
            )
    if remember_classification:
        remember_accounting_rule(
            conn,
            provider_id=values["proveedor_id"],
            category_id=values["categoria_id"],
            subcategory_id=values.get("subcategoria_id"),
            actor=actor,
            invoice_id=invoice_id,
            review_id=review_id,
        )

    conn.execute(
        """
        UPDATE core.facturas SET sucursal_id = %s, sucursal_origen = 'edicion_humana',
            actualizada_en = now() WHERE id = %s
        """,
        (values["sucursal_id"], invoice_id),
    )
    return {"factura_id": invoice_id, "estado": "aprobada", "factura_final_id": final_id}
