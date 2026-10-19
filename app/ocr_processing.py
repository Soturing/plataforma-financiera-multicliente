import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.extraction import extract_invoice_fields
from app.classification import classify_document, is_expense_document, save_classification
from app.branch_detection import apply_detected_branch
from app.ocr.base import OcrDocument
from app.provider_catalog import (
    find_provider,
    find_provider_in_text,
    normalize_provider_rfc,
)
from app.page_groups import group_batch_pages
from app.repository import register_uuid_duplicates


def reading_context(conn: Connection) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """RFC y nombres propios del grupo (receptores, nunca proveedor) y RFC de proveedores conocidos."""
    branches = conn.execute(
        """
        SELECT rfc, razon_social, nombre, restaurante, aliases
        FROM catalog.sucursales WHERE activa AND clave <> 'POR-ASIGNAR'
        """
    ).fetchall()
    own_rfcs: list[str] = []
    own_names: list[str] = []
    for branch in branches:
        if branch["rfc"]:
            own_rfcs.append(branch["rfc"].upper())
        for value in (branch["razon_social"], branch["nombre"], branch["restaurante"], *(branch["aliases"] or [])):
            if value and len(str(value).strip()) >= 4 and str(value) not in own_names:
                own_names.append(str(value))
    for entity in conn.execute(
        "SELECT nombre, rfc FROM catalog.entidades_propias WHERE activa"
    ).fetchall():
        if entity["rfc"]:
            own_rfcs.append(entity["rfc"].upper())
        if len(entity["nombre"].strip()) >= 4 and entity["nombre"] not in own_names:
            own_names.append(entity["nombre"])
    known = tuple(
        row["rfc"].upper() for row in conn.execute(
            "SELECT DISTINCT rfc FROM catalog.proveedores WHERE rfc IS NOT NULL AND activo"
        ).fetchall()
    )
    own_set = set(own_rfcs)
    known = tuple(rfc for rfc in known if rfc not in own_set)  # un RFC propio nunca es de proveedor
    return tuple(dict.fromkeys(own_rfcs)), tuple(own_names), known


def find_possible_duplicates(
    conn: Connection,
    invoice_id: UUID,
    *,
    provider_id: UUID | None,
    total: Decimal | None,
    issue_date: Any,
    folio: str | None,
    folio_origin: str | None,
) -> list[dict[str, Any]]:
    """Documentos del mismo proveedor con el mismo total (y fecha cercana) o el mismo folio.

    Un ticket y su factura son un solo gasto; un folio repetido suele ser la página de continuación
    de una factura. Solo se advierte: la decisión es de la persona que revisa.
    """
    if provider_id is None:
        return []
    rows = conn.execute(
        """
        SELECT f.id, f.archivo_nombre, i.total, i.fecha_emision, i.folio, i.folio_origen
        FROM core.facturas f
        JOIN LATERAL (
            SELECT * FROM ai.interpretaciones ix WHERE ix.factura_id = f.id ORDER BY ix.version DESC LIMIT 1
        ) i ON true
        WHERE f.id <> %s AND i.proveedor_id = %s AND f.estado::text NOT IN ('cancelada', 'rechazada')
        """,
        (invoice_id, provider_id),
    ).fetchall()
    found = []
    for row in rows:
        same_total = (
            total is not None and row["total"] is not None and abs(Decimal(row["total"]) - total) <= Decimal("0.01")
        )
        close_dates = (
            issue_date is None or row["fecha_emision"] is None
            or abs((row["fecha_emision"] - issue_date).days) <= 3
        )
        same_folio = bool(
            folio and row["folio"] and folio_origin == "detectado" and row["folio_origen"] == "detectado"
            and folio.strip().upper() == str(row["folio"]).strip().upper()
        )
        if (same_total and close_dates) or same_folio:
            found.append({
                "factura_id": row["id"], "archivo": row["archivo_nombre"],
                "motivo": "folio" if same_folio and not same_total else "total",
                "folio": row["folio"],
            })
    return found


def persist_ocr_result(
    conn: Connection,
    invoice_id: UUID,
    document: OcrDocument,
) -> dict[str, Any]:
    invoice = conn.execute(
        "SELECT id, estado::text FROM core.facturas WHERE id = %s FOR UPDATE",
        (invoice_id,),
    ).fetchone()
    if not invoice or invoice["estado"] != "ocr_procesando":
        raise ValueError("La factura no está disponible para guardar OCR")

    ocr_version = conn.execute(
        "SELECT COALESCE(max(version), 0) + 1 AS version FROM ocr.resultados WHERE factura_id = %s",
        (invoice_id,),
    ).fetchone()["version"]
    ocr_id = conn.execute(
        """
        INSERT INTO ocr.resultados (
            factura_id, version, proveedor_ocr, modelo_ocr, texto_raw,
            json_raw, confianza, duracion_ms
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        RETURNING id
        """,
        (
            invoice_id, ocr_version, document.provider, document.model, document.text,
            json.dumps(document.raw), document.confidence, document.duration_ms,
        ),
    ).fetchone()["id"]
    conn.execute("UPDATE core.facturas SET estado = 'ocr_completado' WHERE id = %s", (invoice_id,))

    own_rfcs, own_names, known_rfcs = reading_context(conn)
    qr_list = document.raw.get("qr_sat") if isinstance(document.raw, dict) else None
    fields = extract_invoice_fields(
        document.text, own_rfcs=own_rfcs, own_names=own_names, known_rfcs=known_rfcs,
        qr=(qr_list[0] if qr_list else None),
    )
    classification = classify_document(document.text, has_sat_qr=bool(qr_list))
    save_classification(conn, invoice_id, classification)
    provider_id = None
    original_provider_proposal = fields.get("proveedor_propuesto")
    fields["rfc_candidates"] = [
        normalized
        for candidate in fields["rfc_candidates"]
        if (normalized := normalize_provider_rfc(candidate))
    ]
    fields["rfc_emisor"] = normalize_provider_rfc(fields.get("rfc_emisor"))
    provider = find_provider(
        conn,
        rfc=fields.get("rfc_emisor"),
        proposed_name=fields.get("proveedor_propuesto"),
    )
    if provider is None:
        provider = find_provider_in_text(conn, document.text)
    provider_id = provider["id"] if provider else None
    if provider:
        fields["rfc_emisor"] = provider["rfc"] or fields.get("rfc_emisor")
        fields["proveedor_propuesto"] = provider["nombre_normalizado"]
    if provider_id is None and fields["rfc_emisor"]:
        proposed_name = fields["proveedor_propuesto"] or fields["rfc_emisor"]
        provider_id = conn.execute(
            """
            INSERT INTO catalog.proveedores (rfc, nombre_legal, nombre_normalizado)
            VALUES (%s, %s, %s)
            ON CONFLICT (rfc) WHERE rfc IS NOT NULL
            DO UPDATE SET activo = true
            RETURNING id
            """,
            (fields["rfc_emisor"], proposed_name, proposed_name),
        ).fetchone()["id"]

    branch_inference = apply_detected_branch(
        conn,
        invoice_id,
        document.text,
        provider_id=provider_id,
        ocr_result_id=ocr_id,
    )

    accounting_rule = None
    if provider_id and is_expense_document(classification.type):
        accounting_rule = conn.execute(
            """
            SELECT categoria_id, subcategoria_id
            FROM catalog.reglas_clasificacion
            WHERE proveedor_id = %s AND activa
            ORDER BY prioridad, version DESC
            LIMIT 1
            """,
            (provider_id,),
        ).fetchone()
    category_id = (
        accounting_rule["categoria_id"]
        if accounting_rule
        else conn.execute("SELECT id FROM catalog.categorias WHERE clave = 'VARIABLES_OPERATIVOS' AND activa").fetchone()["id"]
    )
    subcategory_id = accounting_rule["subcategoria_id"] if accounting_rule else None
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
            categoria_id, subcategoria_id, confianza, observaciones, salida_json
        ) VALUES (
            %s, %s, %s, 'reglas-deterministicas', '0.2', %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s::jsonb
        ) RETURNING id
        """,
        (
            invoice_id, ocr_id, ia_version, provider_id, fields["proveedor_propuesto"],
            fields["rfc_emisor"], fields["uuid_fiscal"], fields["folio"],
            fields["folio_origen"], fields["fecha_emision"],
            fields["subtotal"], fields["descuento"], fields["iva"],
            fields["otros_impuestos"], fields["total"], category_id,
            subcategory_id, document.confidence,
            (
                "Extracción inicial; requiere revisión humana"
                if is_expense_document(classification.type)
                else f"Documento {classification.type}; fuera del flujo de gastos"
            ),
            json.dumps({
                **fields,
                "proveedor_ocr_original": original_provider_proposal,
                "sucursal_inferencia": branch_inference,
            }, default=str),
        ),
    ).fetchone()["id"]
    if fields["uuid_fiscal"]:
        register_uuid_duplicates(conn, fields["uuid_fiscal"])
    conn.execute("UPDATE core.facturas SET estado = 'validando' WHERE id = %s", (invoice_id,))

    checks = []
    if is_expense_document(classification.type):
        if branch_inference and branch_inference["metodo"] == "consumo":
            if branch_inference["aplicada"]:
                checks.append((
                    "SUCURSAL_POR_CONSUMO", "informativa", True, "sucursal_id",
                    f"{branch_inference['restaurante']} sugerida por productos; confirme la sucursal",
                ))
            else:
                checks.append((
                    "SUCURSAL_POR_CONSUMO", "advertencia", False, "sucursal_id",
                    "La composición de compra sugiere una sucursal, pero requiere confirmación humana",
                ))
        for duplicate in find_possible_duplicates(
            conn, invoice_id, provider_id=provider_id, total=fields["total"],
            issue_date=fields["fecha_emision"], folio=fields["folio"], folio_origin=fields["folio_origen"],
        ):
            reason = (
                "mismo folio: puede ser una página de continuación o un duplicado"
                if duplicate["motivo"] == "folio"
                else "mismo proveedor y total: un ticket y su factura son un solo gasto"
            )
            checks.append((
                "POSIBLE_DUPLICADO", "advertencia", False, "total",
                f"Parecido a {duplicate['archivo']} ({reason}); verifique antes de aprobar",
            ))
        checks.append(("PROVEEDOR", "error", provider_id is not None, "proveedor", "Proveedor identificado" if provider_id else "Proveedor requiere selección"))
        checks.append(("FECHA", "error", fields["fecha_emision"] is not None, "fecha_emision", "Fecha identificada" if fields["fecha_emision"] else "Fecha no identificada"))
        total_present = fields["total"] is not None and fields["total"] > 0
        checks.append(("TOTAL_PRESENTE", "error", total_present, "total", "Total identificado" if total_present else "Total no identificado"))
        if classification.type == "factura_fiscal":
            total_ok = None
            if fields["subtotal"] is not None and fields["total"] is not None:
                calculated = (
                    fields["subtotal"]
                    - (fields["descuento"] or Decimal("0"))
                    + (fields["iva"] or Decimal("0"))
                    + (fields["otros_impuestos"] or Decimal("0"))
                )
                total_ok = abs(calculated - fields["total"]) <= Decimal("0.02")
            if total_ok is None:
                checks.append((
                    "DESGLOSE_INCOMPLETO", "advertencia", False, "subtotal",
                    "Subtotal o impuestos no identificados; valide el total para aprobar",
                ))
            else:
                checks.append((
                    "CUADRE_TOTAL", "advertencia", total_ok, "total",
                    "Los importes cuadran" if total_ok else "El desglose no cuadra; puede aprobarse verificando el total",
                ))
        else:
            checks.append((
                "DOCUMENTO_SIN_CFDI", "informativa", True, None,
                "Comprobante de gasto sin CFDI; se registrará como no deducible",
            ))
    else:
        checks.append((
            "DOCUMENTO_NO_CONTABILIZABLE", "informativa", False, None,
            "Documento separado del flujo de gastos; archivar después de revisarlo",
        ))
    checks.append(("REVISION_PILOTO", "informativa", False, None, "La v0.1 requiere revisión humana"))
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.validaciones
                (factura_id, interpretacion_id, codigo, severidad, aprobada, campo, mensaje)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [(invoice_id, interpretation_id, *check) for check in checks],
        )
    conn.execute(
        "UPDATE core.facturas SET estado = 'requiere_revision', actualizada_en = now(), error_codigo = NULL, error_detalle = NULL WHERE id = %s",
        (invoice_id,),
    )
    batch = conn.execute("SELECT lote_id FROM core.facturas WHERE id = %s", (invoice_id,)).fetchone()
    group_batch_pages(conn, batch["lote_id"] if batch else None)
    return {"interpretation_id": interpretation_id, "fields": fields}


def claim_batch_invoices(conn: Connection, batch_id: UUID) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, archivo_url FROM core.facturas
        WHERE lote_id = %s AND estado IN ('recibida', 'error', 'ocr_procesando')
        ORDER BY pagina_origen
        FOR UPDATE SKIP LOCKED
        """,
        (batch_id,),
    ).fetchall()
    return rows
