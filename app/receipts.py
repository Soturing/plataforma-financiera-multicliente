import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.errors import DomainError
from app.fixed_expenses import require_fixed_provider
from app.periodification import save_periodification


RECEIPT_SELECT = """
SELECT ci.id, ci.folio, ci.numero_documento, ci.numero_documento_origen,
       ci.fecha_gasto, ci.concepto, ci.metodo_pago,
       ci.total, ci.moneda, ci.estado, ci.estado_fiscal,
       ci.aprobaciones_requeridas, ci.creado_por, ci.rol_creador,
       ci.firma_proveedor_nombre, ci.firma_proveedor_confirmada,
       ci.evidencia_nombre, ci.evidencia_mime,
       ci.primera_aprobacion_por, ci.primera_aprobacion_en,
       ci.primera_aprobacion_comentario, ci.segunda_aprobacion_por,
       ci.segunda_aprobacion_en, ci.segunda_aprobacion_comentario,
       ci.rechazado_por, ci.rechazado_en, ci.motivo_rechazo,
       ci.factura_final_reemplazo_id, ci.creado_en, ci.actualizado_en,
       s.id AS sucursal_id, s.clave AS sucursal_clave, s.nombre AS sucursal,
       s.restaurante, p.id AS proveedor_id, p.nombre_normalizado AS proveedor,
       p.telefono AS proveedor_telefono, p.giro AS proveedor_giro,
       c.id AS categoria_id, c.nombre AS categoria,
       sc.id AS subcategoria_id, sc.nombre AS subcategoria,
       COALESCE((
           SELECT jsonb_agg(jsonb_build_object(
               'sucursal_id', ds.id, 'sucursal_clave', ds.clave,
               'sucursal', ds.nombre, 'restaurante', ds.restaurante,
               'monto', d.monto
           ) ORDER BY ds.restaurante, ds.nombre)
           FROM core.comprobante_distribuciones d
           JOIN catalog.sucursales ds ON ds.id = d.sucursal_id
           WHERE d.comprobante_id = ci.id
       ), '[]'::jsonb) AS distribuciones
FROM core.comprobantes_internos ci
JOIN catalog.sucursales s ON s.id = ci.sucursal_id
JOIN catalog.proveedores p ON p.id = ci.proveedor_id
JOIN catalog.categorias c ON c.id = ci.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ci.subcategoria_id
"""


def _receipt(conn: Connection, receipt_id: UUID) -> dict[str, Any]:
    row = conn.execute(RECEIPT_SELECT + " WHERE ci.id = %s", (receipt_id,)).fetchone()
    if not row:
        raise DomainError("Comprobante interno no encontrado.", 404)
    return row


def _catalog_id(conn: Connection, table: str, identifier: UUID, *, active: str) -> UUID:
    allowed = {
        "categorias": "catalog.categorias",
        "subcategorias": "catalog.subcategorias",
    }
    if table not in allowed:
        raise RuntimeError("Catálogo no permitido")
    row = conn.execute(
        f"SELECT id FROM {allowed[table]} WHERE id = %s AND {active}", (identifier,)  # nosec B608
        # Motivo: tabla de una lista blanca; el id va como parámetro
    ).fetchone()
    if not row:
        raise DomainError(f"El valor de {table} no existe o está inactivo.", 422)
    return row["id"]


def create_internal_receipt(
    conn: Connection,
    *,
    sucursal_clave: str,
    proveedor_nombre: str,
    numero_documento: str | None,
    proveedor_telefono: str | None,
    proveedor_giro: str | None,
    fecha_gasto: date,
    concepto: str,
    metodo_pago: str,
    total: Decimal,
    categoria_id: UUID,
    subcategoria_id: UUID | None,
    creado_por: str,
    rol_creador: str,
    firma_proveedor_nombre: str | None,
    firma_proveedor_confirmada: bool,
    distribuciones: list[dict[str, Any]] | None,
    evidencia: dict[str, str] | None = None,
    periodificacion: dict[str, Any] | None = None,
    recordar_periodificacion: bool = False,
) -> dict[str, Any]:
    proveedor_nombre = proveedor_nombre.strip()
    numero_capturado = bool((numero_documento or "").strip())
    numero_documento = (numero_documento or "").strip() or fecha_gasto.strftime("%d%m%Y")
    numero_documento_origen = "capturado" if numero_capturado else "fecha"
    concepto = concepto.strip()
    creado_por = creado_por.strip()
    if not proveedor_nombre or not concepto or not creado_por:
        raise DomainError("Proveedor, concepto y responsable son obligatorios.", 422)
    if metodo_pago not in {"efectivo", "transferencia", "tarjeta", "otro"}:
        raise DomainError("Método de pago no válido.", 422)
    if rol_creador not in {"gerente", "capturista"}:
        raise DomainError("El rol debe ser gerente o capturista.", 422)
    if total <= 0 or total > Decimal("300000"):
        raise DomainError("El importe debe ser mayor a $0 y no superar $300,000.", 422)
    if metodo_pago == "efectivo" and (
        not firma_proveedor_confirmada or not (firma_proveedor_nombre or "").strip()
    ):
        raise DomainError("En pagos en efectivo, la firma del proveedor es obligatoria.", 422)

    branch = conn.execute(
        "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa", (sucursal_clave,)
    ).fetchone()
    if not branch:
        raise DomainError("Sucursal no encontrada o inactiva.", 422)
    category = conn.execute(
        "SELECT id, clave, nombre, admite_facturas FROM catalog.categorias WHERE id = %s AND activa",
        (categoria_id,),
    ).fetchone()
    if not category:
        raise DomainError("El valor de categorias no existe o está inactivo.", 422)
    if not category["admite_facturas"]:
        raise DomainError(
            f"La categoría {category['nombre']} no se captura con comprobantes; se registra por separado.", 422
        )
    if subcategoria_id:
        valid_subcategory = conn.execute(
            "SELECT 1 FROM catalog.subcategorias WHERE id = %s AND categoria_id = %s AND activa",
            (subcategoria_id, categoria_id),
        ).fetchone()
        if not valid_subcategory:
            raise DomainError("La subcategoría no corresponde a la categoría seleccionada.", 422)

    provider = conn.execute(
        "SELECT id FROM catalog.proveedores WHERE lower(nombre_normalizado) = lower(%s) ORDER BY creado_en LIMIT 1",
        (proveedor_nombre,),
    ).fetchone()
    if provider:
        provider_id = provider["id"]
        conn.execute(
            """
            UPDATE catalog.proveedores SET es_informal = true,
                telefono = COALESCE(NULLIF(%s, ''), telefono),
                giro = COALESCE(NULLIF(%s, ''), giro)
            WHERE id = %s
            """,
            (proveedor_telefono, proveedor_giro, provider_id),
        )
    else:
        provider_id = conn.execute(
            """
            INSERT INTO catalog.proveedores
                (nombre_legal, nombre_normalizado, es_informal, telefono, giro)
            VALUES (%s, %s, true, NULLIF(%s, ''), NULLIF(%s, '')) RETURNING id
            """,
            (proveedor_nombre, proveedor_nombre, proveedor_telefono, proveedor_giro),
        ).fetchone()["id"]

    if category["clave"] == "FIJOS":
        require_fixed_provider(conn, provider_id)

    parsed_distributions = distribuciones or [{"sucursal_clave": sucursal_clave, "monto": total}]
    if not parsed_distributions:
        raise DomainError("Agrega al menos una distribución del gasto.", 422)
    if len(parsed_distributions) != 1 or str(parsed_distributions[0].get("sucursal_clave", "")).strip() != sucursal_clave:
        raise DomainError("Los pagos cruzados no están permitidos; cada gasto pertenece a una sola sucursal.", 422)
    keys = [str(item.get("sucursal_clave", "")).strip() for item in parsed_distributions]
    if len(keys) != len(set(keys)):
        raise DomainError("Una sucursal no puede repetirse en la distribución.", 422)
    try:
        allocated = sum((Decimal(str(item["monto"])) for item in parsed_distributions), Decimal("0"))
    except (KeyError, ValueError, TypeError):
        raise DomainError("La distribución contiene un importe inválido.", 422)
    if allocated != total or any(Decimal(str(item["monto"])) <= 0 for item in parsed_distributions):
        raise DomainError("La distribución debe sumar exactamente el total y usar importes positivos.", 422)

    branch_rows = conn.execute(
        "SELECT id, clave FROM catalog.sucursales WHERE clave = ANY(%s) AND activa", (keys,)
    ).fetchall()
    branch_ids = {row["clave"]: row["id"] for row in branch_rows}
    if len(branch_ids) != len(keys):
        raise DomainError("Una de las sucursales de la distribución no existe o está inactiva.", 422)

    approvals = 1
    receipt = conn.execute(
        """
        INSERT INTO core.comprobantes_internos (
            sucursal_id, proveedor_id, numero_documento, numero_documento_origen,
            fecha_gasto, concepto, metodo_pago, total,
            categoria_id, subcategoria_id, creado_por, rol_creador,
            firma_proveedor_nombre, firma_proveedor_confirmada, firma_proveedor_en,
            evidencia_url, evidencia_nombre, evidencia_mime, evidencia_sha256,
            estado, aprobaciones_requeridas
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            CASE WHEN %s THEN now() ELSE NULL END,
            %s, %s, %s, %s, 'pendiente_aprobacion', %s
        ) RETURNING id
        """,
        (
            branch["id"], provider_id, numero_documento, numero_documento_origen,
            fecha_gasto, concepto, metodo_pago, total,
            categoria_id, subcategoria_id, creado_por, rol_creador,
            (firma_proveedor_nombre or "").strip() or None, firma_proveedor_confirmada,
            firma_proveedor_confirmada,
            evidencia and evidencia["path"], evidencia and evidencia["name"],
            evidencia and evidencia["mime"], evidencia and evidencia["sha256"], approvals,
        ),
    ).fetchone()
    for item in parsed_distributions:
        conn.execute(
            """
            INSERT INTO core.comprobante_distribuciones (comprobante_id, sucursal_id, monto)
            VALUES (%s, %s, %s)
            """,
            (receipt["id"], branch_ids[item["sucursal_clave"]], Decimal(str(item["monto"]))),
        )
    save_periodification(
        conn,
        receipt_id=receipt["id"],
        total=total,
        category_key=category["clave"],
        provider_id=provider_id,
        subcategory_id=subcategoria_id,
        config=periodificacion,
        actor=creado_por,
        remember=recordar_periodificacion,
    )
    return _receipt(conn, receipt["id"])


def parse_distributions(value: str | None) -> list[dict[str, Any]] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise DomainError("La distribución no tiene un formato JSON válido.", 422)
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise DomainError("La distribución debe ser una lista.", 422)
    return parsed


def list_internal_receipts(
    conn: Connection, *, limit: int = 50, offset: int = 0, state: str | None = None
) -> list[dict[str, Any]]:
    where = " WHERE ci.estado = %s" if state else ""
    params: tuple[Any, ...] = (state, limit, offset) if state else (limit, offset)
    return conn.execute(
        RECEIPT_SELECT + where + " ORDER BY ci.creado_en DESC LIMIT %s OFFSET %s", params
    ).fetchall()


def get_internal_receipt(conn: Connection, receipt_id: UUID) -> dict[str, Any]:
    return _receipt(conn, receipt_id)


def approve_internal_receipt(
    conn: Connection, receipt_id: UUID, *, actor: str, comment: str | None = None
) -> dict[str, Any]:
    actor = actor.strip()
    if not actor:
        raise DomainError("Indica quién autoriza el comprobante.", 422)
    row = conn.execute(
        "SELECT * FROM core.comprobantes_internos WHERE id = %s FOR UPDATE", (receipt_id,)
    ).fetchone()
    if not row:
        raise DomainError("Comprobante interno no encontrado.", 404)
    if row["estado"] == "pendiente_aprobacion":
        next_state = "aprobado"
        conn.execute(
            """
            UPDATE core.comprobantes_internos SET estado = %s,
                primera_aprobacion_por = %s, primera_aprobacion_en = now(),
                primera_aprobacion_comentario = %s, actualizado_en = now()
            WHERE id = %s
            """,
            (next_state, actor, comment, receipt_id),
        )
    else:
        raise DomainError(f"El comprobante no puede aprobarse desde el estado {row['estado']}.", 409)
    return _receipt(conn, receipt_id)


def reject_internal_receipt(
    conn: Connection, receipt_id: UUID, *, actor: str, reason: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT estado FROM core.comprobantes_internos WHERE id = %s FOR UPDATE", (receipt_id,)
    ).fetchone()
    if not row:
        raise DomainError("Comprobante interno no encontrado.", 404)
    if row["estado"] != "pendiente_aprobacion":
        raise DomainError("Solo se pueden rechazar comprobantes pendientes.", 409)
    conn.execute(
        """
        UPDATE core.comprobantes_internos SET estado = 'rechazado', rechazado_por = %s,
            rechazado_en = now(), motivo_rechazo = %s, actualizado_en = now()
        WHERE id = %s
        """,
        (actor.strip(), reason.strip(), receipt_id),
    )
    return _receipt(conn, receipt_id)


def replace_internal_receipt(
    conn: Connection, receipt_id: UUID, *, invoice_final_id: UUID
) -> dict[str, Any]:
    invoice = conn.execute(
        "SELECT id FROM core.facturas_finales WHERE id = %s AND vigente", (invoice_final_id,)
    ).fetchone()
    if not invoice:
        raise DomainError("La factura fiscal final no existe o ya no está vigente.", 422)
    row = conn.execute(
        "SELECT estado FROM core.comprobantes_internos WHERE id = %s FOR UPDATE", (receipt_id,)
    ).fetchone()
    if not row:
        raise DomainError("Comprobante interno no encontrado.", 404)
    if row["estado"] != "aprobado":
        raise DomainError("Solo un comprobante aprobado puede sustituirse por un CFDI.", 409)
    conn.execute(
        """
        UPDATE core.comprobantes_internos SET estado = 'sustituido', estado_fiscal = 'con_cfdi',
            factura_final_reemplazo_id = %s, sustituido_en = now(), actualizado_en = now()
        WHERE id = %s
        """,
        (invoice_final_id, receipt_id),
    )
    return _receipt(conn, receipt_id)


def evidence_path(conn: Connection, receipt_id: UUID) -> tuple[Path, str, str]:
    row = conn.execute(
        "SELECT evidencia_url, evidencia_nombre, evidencia_mime FROM core.comprobantes_internos WHERE id = %s",
        (receipt_id,),
    ).fetchone()
    if not row:
        raise DomainError("Comprobante interno no encontrado.", 404)
    if not row["evidencia_url"]:
        raise DomainError("Este comprobante no tiene evidencia anexa.", 404)
    return Path(row["evidencia_url"]), row["evidencia_nombre"], row["evidencia_mime"]
