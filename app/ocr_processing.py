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
    known = tuple(
        row["rfc"].upper() for row in conn.execute(
            "SELECT DISTINCT rfc FROM catalog.proveedores WHERE rfc IS NOT NULL AND activo"
        ).fetchall()
    )
    return tuple(dict.fromkeys(own_rfcs)), tuple(own_names), known


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
