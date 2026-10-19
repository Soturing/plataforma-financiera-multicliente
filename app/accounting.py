import json
import re
from calendar import monthrange
from datetime import date, timedelta
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.errors import DomainError
from app.commissions import weekly_commissions


def _clean_key(value: str) -> str:
    key = re.sub(r"[^A-Z0-9_]+", "_", value.strip().upper()).strip("_")
    if not re.fullmatch(r"[A-Z0-9_]{2,50}", key):
        raise DomainError("La clave debe contener entre 2 y 50 letras, números o guiones bajos.", 422)
    return key


def list_accounting_catalogs(conn: Connection) -> dict[str, list[dict[str, Any]]]:
    categories = conn.execute(
        """
        SELECT id, clave, nombre, activa, orden, tipo_costo, admite_facturas,
               (SELECT count(*) FROM catalog.subcategorias sc WHERE sc.categoria_id = c.id)::integer AS subcategorias
        FROM catalog.categorias c
        WHERE activa
        ORDER BY orden
        """
    ).fetchall()
    subcategories = conn.execute(
        """
        SELECT sc.id, sc.categoria_id, c.clave AS categoria, sc.clave, sc.nombre, sc.activa,
               (
                   (SELECT count(*) FROM ai.interpretaciones i WHERE i.subcategoria_id = sc.id) +
                   (SELECT count(*) FROM core.facturas_finales f WHERE f.subcategoria_id = sc.id) +
                   (SELECT count(*) FROM core.comprobantes_internos ci WHERE ci.subcategoria_id = sc.id)
               )::integer AS usos
        FROM catalog.subcategorias sc
        JOIN catalog.categorias c ON c.id = sc.categoria_id
        WHERE c.activa
        ORDER BY c.orden, sc.nombre
        """
    ).fetchall()
    return {
        "categorias": categories,
        "subcategorias": subcategories,
    }


def _audit_catalog(
    conn: Connection,
    *,
    entity: str,
    entity_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    actor: str,
) -> None:
    conn.execute(
        """
        INSERT INTO audit.cambios_catalogo (
            entidad, entidad_id, accion, antes, despues, realizado_por
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
        """,
        (
            entity,
            entity_id,
            action,
            json.dumps(before, default=str) if before else None,
            json.dumps(after, default=str),
            actor,
        ),
    )


def save_subcategory(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    item_id = data.get("id")
    key = _clean_key(data["clave"])
    name = str(data["nombre"]).strip()
    category = conn.execute(
        "SELECT id, clave FROM catalog.categorias WHERE id = %s AND activa AND admite_facturas",
        (data["categoria_id"],),
    ).fetchone()
    if not category:
        raise DomainError("La categoría no existe o no admite subcategorías.", 422)
    before = None
    if item_id:
        before = conn.execute(
            "SELECT id, categoria_id, clave, nombre, activa FROM catalog.subcategorias WHERE id = %s",
            (item_id,),
        ).fetchone()
        if not before:
            raise DomainError("Subcategoría no encontrada.", 404)
        if before["categoria_id"] != category["id"]:
            used = conn.execute(
                """
                SELECT EXISTS(SELECT 1 FROM core.facturas_finales WHERE subcategoria_id = %s)
                    OR EXISTS(SELECT 1 FROM core.comprobantes_internos WHERE subcategoria_id = %s) AS usada
                """,
                (item_id, item_id),
            ).fetchone()["usada"]
            if used:
                raise DomainError("No se puede cambiar de categoría una subcategoría con movimientos publicados.", 409)
        row = conn.execute(
            """
            UPDATE catalog.subcategorias
            SET categoria_id = %s, clave = %s, nombre = %s, activa = %s
            WHERE id = %s
            RETURNING id, categoria_id, clave, nombre, activa
            """,
            (category["id"], key, name, bool(data.get("activa", True)), item_id),
        ).fetchone()
        action = "actualizar"
        if before["activa"] != row["activa"]:
            action = "activar" if row["activa"] else "desactivar"
    else:
        existing = conn.execute(
            "SELECT id FROM catalog.subcategorias WHERE categoria_id = %s AND clave = %s",
            (category["id"], key),
        ).fetchone()
        if existing:
            raise DomainError("Ya existe esa clave dentro de la categoría.", 409)
        row = conn.execute(
            """
            INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
            VALUES (%s, %s, %s, %s)
            RETURNING id, categoria_id, clave, nombre, activa
            """,
            (category["id"], key, name, bool(data.get("activa", True))),
        ).fetchone()
        action = "crear"
    _audit_catalog(
        conn, entity="subcategoria", entity_id=row["id"], action=action,
        before=before, after=row, actor=actor,
    )
    return {**row, "categoria": category["clave"]}


def register_sale(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    branch = conn.execute(
        "SELECT id, clave FROM catalog.sucursales WHERE id = %s AND activa",
        (data["sucursal_id"],),
    ).fetchone()
    if not branch or branch["clave"] == "POR-ASIGNAR":
        raise DomainError("Seleccione una sucursal operativa.", 422)
    return conn.execute(
        """
        INSERT INTO finance.ventas (
            sucursal_id, fecha, monto_neto, fuente, referencia, es_demo, registrada_por
        ) VALUES (%s, %s, %s, 'manual', %s, false, %s)
        ON CONFLICT (sucursal_id, fecha) DO UPDATE SET
            monto_neto = EXCLUDED.monto_neto,
            fuente = 'manual', referencia = EXCLUDED.referencia,
            es_demo = false, registrada_por = EXCLUDED.registrada_por,
            total_capturado_manual = true, actualizada_en = now()
        RETURNING id, sucursal_id, fecha, monto_neto, fuente, referencia, es_demo
        """,
        (
            branch["id"], data["fecha"], data["monto_neto"],
            data.get("referencia") or f"MANUAL-{data['fecha'].isoformat()}", actor,
        ),
    ).fetchone()


SALES_FIELDS = (
    "efectivo", "dolares", "tipo_cambio", "rappi", "uber", "visa", "amex",
    "venta_otro", "venta_aplicaciones", "venta_alimentos", "venta_bebidas",
    "visitas", "faltante", "sobrante",
)


def _sales_metrics(row: dict[str, Any]) -> dict[str, Any]:
    usd_conversion = Decimal(row.get("dolares") or 0) * Decimal(row.get("tipo_cambio") or 0)
    credit = Decimal(row.get("visa") or 0) + Decimal(row.get("amex") or 0)
    calculated = (
        Decimal(row.get("efectivo") or 0) + usd_conversion
        + Decimal(row.get("rappi") or 0) + Decimal(row.get("uber") or 0) + credit
    )
    net = Decimal(row.get("monto_neto") or 0)
    mix = sum(
        (Decimal(row.get(field) or 0) for field in (
            "venta_otro", "venta_aplicaciones", "venta_alimentos", "venta_bebidas"
        )),
        Decimal("0"),
    )
    visits = int(row.get("visitas") or 0)
    return {
        **row,
        "conversion_usd": usd_conversion,
        "credito": credit,
        "total_calculado": calculated,
        "monto_neto": net,
        "total_mix": mix,
        "diferencia_desglose": mix - net,
        "ticket_promedio": net / visits if visits else None,
    }


def get_sales_breakdown(
    conn: Connection,
    *,
    anio_iso: int,
    semana_iso: int,
    sucursal_clave: str | None = None,
) -> dict[str, Any]:
    try:
        date_from = date.fromisocalendar(anio_iso, semana_iso, 1)
        date_to = date.fromisocalendar(anio_iso, semana_iso, 7)
    except ValueError as exc:
        raise DomainError("La semana ISO indicada no existe.", 422) from exc
    if sucursal_clave:
        branch = conn.execute(
            "SELECT id, clave, nombre, restaurante FROM catalog.sucursales WHERE clave = %s AND activa",
            (sucursal_clave,),
        ).fetchone()
        if not branch or branch["clave"] == "POR-ASIGNAR":
            raise DomainError("Sucursal no disponible para captura de ventas.", 422)
        rows = conn.execute(
            """
            SELECT id, sucursal_id, fecha, monto_neto, fuente, referencia, es_demo,
                   efectivo, dolares, tipo_cambio, rappi, uber, visa, amex,
                   venta_otro, venta_aplicaciones, venta_alimentos, venta_bebidas,
                   visitas, faltante, sobrante, total_capturado_manual
            FROM finance.ventas
            WHERE sucursal_id = %s AND fecha BETWEEN %s AND %s
            ORDER BY fecha
            """,
            (branch["id"], date_from, date_to),
        ).fetchall()
    else:
        branch = None
        rows = conn.execute(
            """
            SELECT NULL::uuid AS id, NULL::uuid AS sucursal_id, fecha,
                   sum(monto_neto)::numeric(14,2) AS monto_neto,
                   'consolidado'::text AS fuente, 'CONSOLIDADO'::text AS referencia,
                   bool_and(es_demo) AS es_demo,
                   sum(efectivo)::numeric(14,2) AS efectivo,
                   sum(dolares)::numeric(14,2) AS dolares,
                   CASE WHEN sum(dolares) > 0
                        THEN sum(dolares * tipo_cambio) / sum(dolares) ELSE 0 END AS tipo_cambio,
                   sum(rappi)::numeric(14,2) AS rappi,
                   sum(uber)::numeric(14,2) AS uber,
                   sum(visa)::numeric(14,2) AS visa,
                   sum(amex)::numeric(14,2) AS amex,
                   sum(venta_otro)::numeric(14,2) AS venta_otro,
                   sum(venta_aplicaciones)::numeric(14,2) AS venta_aplicaciones,
                   sum(venta_alimentos)::numeric(14,2) AS venta_alimentos,
                   sum(venta_bebidas)::numeric(14,2) AS venta_bebidas,
                   sum(visitas)::integer AS visitas,
                   sum(faltante)::numeric(14,2) AS faltante,
                   sum(sobrante)::numeric(14,2) AS sobrante,
                   bool_or(total_capturado_manual) AS total_capturado_manual
            FROM finance.ventas
            WHERE fecha BETWEEN %s AND %s
            GROUP BY fecha ORDER BY fecha
            """,
            (date_from, date_to),
        ).fetchall()
    contributing_branches = []
    if branch is None:
        contributing_branches = conn.execute(
            """
            SELECT s.clave, s.nombre, s.restaurante,
                   sum(v.monto_neto)::numeric(14,2) AS monto_neto
            FROM finance.ventas v
            JOIN catalog.sucursales s ON s.id = v.sucursal_id
            WHERE v.fecha BETWEEN %s AND %s AND s.clave <> 'POR-ASIGNAR'
            GROUP BY s.id, s.clave, s.nombre, s.restaurante
            HAVING sum(v.monto_neto) <> 0
            ORDER BY s.restaurante, s.nombre
            """,
            (date_from, date_to),
        ).fetchall()
    by_date = {row["fecha"]: _sales_metrics(dict(row)) for row in rows}
    filled = []
    for day_offset in range(7):
        current = date_from.fromordinal(date_from.toordinal() + day_offset)
        row = by_date.get(current) or {
            "id": None, "sucursal_id": branch["id"] if branch else None,
            "fecha": current, "monto_neto": Decimal("0"), "fuente": "sin_captura",
            "referencia": None, "es_demo": False, "total_capturado_manual": False,
            **{field: 0 for field in SALES_FIELDS},
        }
        filled.append(_sales_metrics(dict(row)))
    totals_source: dict[str, Any] = {
        field: sum((Decimal(item.get(field) or 0) for item in filled), Decimal("0"))
        for field in SALES_FIELDS if field != "visitas"
    }
    totals_source["visitas"] = sum(int(item.get("visitas") or 0) for item in filled)
    totals_source["monto_neto"] = sum((item["monto_neto"] for item in filled), Decimal("0"))
    totals_source["dolares"] = sum((Decimal(item["dolares"] or 0) for item in filled), Decimal("0"))
    total_conversion = sum((item["conversion_usd"] for item in filled), Decimal("0"))
    totals_source["tipo_cambio"] = (
        total_conversion / totals_source["dolares"] if totals_source["dolares"] else Decimal("0")
    )
    totals = _sales_metrics(totals_source)
    return {
        "periodo": {
            "anio_iso": anio_iso, "semana_iso": semana_iso,
            "fecha_desde": date_from, "fecha_hasta": date_to,
        },
        "sucursal": branch,
        "editable": branch is not None,
        "alcance": {
            "tipo": "sucursal" if branch else "consolidado",
            "sucursales_con_datos": [dict(item) for item in contributing_branches],
            "cantidad_sucursales": len(contributing_branches),
        },
        "filas": filled,
        "totales": totals,
    }


def save_sales_breakdown(
    conn: Connection,
    *,
    branch_id: UUID,
    rows: list[dict[str, Any]],
    actor: str,
    expenses: list[dict[str, Any]] | None = None,
    source_filename: str | None = None,
) -> dict[str, Any]:
    branch = conn.execute(
        "SELECT id, clave FROM catalog.sucursales WHERE id = %s AND activa",
        (branch_id,),
    ).fetchone()
    if not branch or branch["clave"] == "POR-ASIGNAR":
        raise DomainError("Seleccione una sucursal operativa.", 422)
    saved = 0
    for item in rows:
        conversion = Decimal(item.get("dolares") or 0) * Decimal(item.get("tipo_cambio") or 0)
        calculated = sum(
            (Decimal(item.get(field) or 0) for field in ("efectivo", "rappi", "uber", "visa", "amex")),
            conversion,
        )
        manual = bool(item.get("total_capturado_manual"))
        net = Decimal(item.get("monto_neto") or 0) if manual else calculated
        values = [item.get(field) or 0 for field in SALES_FIELDS]
        conn.execute(
            """
            INSERT INTO finance.ventas (
                sucursal_id, fecha, monto_neto, fuente, referencia, es_demo, registrada_por,
                efectivo, dolares, tipo_cambio, rappi, uber, visa, amex,
                venta_otro, venta_aplicaciones, venta_alimentos, venta_bebidas,
                visitas, faltante, sobrante, total_capturado_manual
            ) VALUES (
                %s, %s, %s, 'manual', %s, false, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (sucursal_id, fecha) DO UPDATE SET
                monto_neto = EXCLUDED.monto_neto, fuente = 'manual',
                referencia = EXCLUDED.referencia, es_demo = false,
                registrada_por = EXCLUDED.registrada_por,
                efectivo = EXCLUDED.efectivo, dolares = EXCLUDED.dolares,
                tipo_cambio = EXCLUDED.tipo_cambio, rappi = EXCLUDED.rappi,
                uber = EXCLUDED.uber, visa = EXCLUDED.visa, amex = EXCLUDED.amex,
                venta_otro = EXCLUDED.venta_otro,
                venta_aplicaciones = EXCLUDED.venta_aplicaciones,
                venta_alimentos = EXCLUDED.venta_alimentos,
                venta_bebidas = EXCLUDED.venta_bebidas,
                visitas = EXCLUDED.visitas, faltante = EXCLUDED.faltante,
                sobrante = EXCLUDED.sobrante,
                total_capturado_manual = EXCLUDED.total_capturado_manual,
                actualizada_en = now()
            """,
            (
                branch["id"], item["fecha"], net,
                f"CAPTURA-{item['fecha'].isoformat()}", actor, *values, manual,
            ),
        )
        saved += 1
    sample = rows[0]["fecha"].isocalendar()
    expense_result = _save_weekly_report_expenses(
        conn,
        branch_id=branch["id"],
        expenses=[item for item in (expenses or []) if item.get("incluir", True)],
        actor=actor,
        source_filename=source_filename,
    )
    return {
        "guardadas": saved,
        "sucursal_clave": branch["clave"],
        "anio_iso": sample.year,
        "semana_iso": sample.week,
        "gastos_creados": expense_result["created"],
        "gastos_existentes": expense_result["existing"],
    }


def _save_weekly_report_expenses(
    conn: Connection,
    *,
    branch_id: UUID,
    expenses: list[dict[str, Any]],
    actor: str,
    source_filename: str | None,
) -> dict[str, int]:
    if not expenses:
        return {"created": 0, "existing": 0}
    catalogs = conn.execute(
        """
        SELECT cb.id AS categoria_barra_id, sb.id AS bebidas_id,
               cr.id AS categoria_restaurante_id, si.id AS insumos_id
        FROM catalog.categorias cb
        JOIN catalog.subcategorias sb ON sb.categoria_id = cb.id AND sb.clave = 'BEBIDAS' AND sb.activa
        JOIN catalog.categorias cr ON cr.clave = 'GASTOS_RESTAURANTE' AND cr.activa
        JOIN catalog.subcategorias si ON si.categoria_id = cr.id AND si.clave = 'INSUMOS' AND si.activa
        WHERE cb.clave = 'GASTOS_BARRA' AND cb.activa
        """
    ).fetchone()
    if not catalogs:
        raise DomainError("No están disponibles los catálogos de Barra y Restaurante.", 422)
    created = 0
    existing = 0
    for item in expenses:
        provider_name = str(item["proveedor"]).strip()
        provider = conn.execute(
            "SELECT id FROM catalog.proveedores WHERE lower(nombre_normalizado) = lower(%s) ORDER BY creado_en LIMIT 1",
            (provider_name,),
        ).fetchone()
        if provider:
            provider_id = provider["id"]
        else:
            provider_id = conn.execute(
                """
                INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado, es_informal)
                VALUES (%s, %s, true) RETURNING id
                """,
                (provider_name, provider_name),
            ).fetchone()["id"]
        area = item["area"]
        fingerprint_text = "|".join(
            str(value or "").strip().upper()
            for value in (
                branch_id, item["fecha"], item["semana"], area, provider_name,
                item["monto"], item.get("numero_factura"), item["descripcion"],
            )
        )
        reference = hashlib.sha256(fingerprint_text.encode("utf-8")).hexdigest()
        payment = str(item.get("pago") or "otro").lower()
        payment = "efectivo" if "efectivo" in payment else "transferencia" if "transfer" in payment else "tarjeta" if "tarjet" in payment else "otro"
        number = (item.get("numero_factura") or "").strip() or f"S{item['semana']:02d}-{area.upper()}-{reference[:8]}"
        receipt = conn.execute(
            """
            INSERT INTO core.comprobantes_internos (
                sucursal_id, proveedor_id, numero_documento, numero_documento_origen,
                fecha_gasto, concepto, metodo_pago, total, categoria_id,
                subcategoria_id, creado_por, rol_creador,
                estado, aprobaciones_requeridas, primera_aprobacion_por,
                primera_aprobacion_en, primera_aprobacion_comentario,
                origen, referencia_origen
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'capturista',
                'aprobado', 1, %s, now(), %s, 'reporte_semanal', %s
            )
            ON CONFLICT (sucursal_id, referencia_origen)
                WHERE origen = 'reporte_semanal' AND referencia_origen IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            (
                branch_id, provider_id, number,
                "capturado" if item.get("numero_factura") else "reporte_semanal",
                item["fecha"], item["descripcion"], payment, item["monto"],
                catalogs["categoria_barra_id"] if area == "barra" else catalogs["categoria_restaurante_id"],
                catalogs["bebidas_id"] if area == "barra" else catalogs["insumos_id"],
                actor, actor, f"Importado desde {source_filename or 'reporte semanal'}",
                reference,
            ),
        ).fetchone()
        if not receipt:
            existing += 1
            continue
        conn.execute(
            """
            INSERT INTO core.comprobante_distribuciones (comprobante_id, sucursal_id, monto)
            VALUES (%s, %s, %s)
            """,
            (receipt["id"], branch_id, item["monto"]),
        )
        created += 1
    return {"created": created, "existing": existing}


def _financial_metrics(row: dict[str, Any]) -> dict[str, Any]:
    sales = Decimal(row.get("ventas") or 0)
    variable = Decimal(row.get("costos_variables") or 0)
    fixed_documented = Decimal(row.get("gastos_fijos_documentados", row.get("gastos_fijos")) or 0)
    fixed_base_value = row.get("base_fija_equilibrio")
    fixed_base = Decimal(fixed_base_value if fixed_base_value is not None else fixed_documented)
    fixed = fixed_base if fixed_base_value is not None else fixed_documented
    contribution = sales - variable
    contribution_rate = contribution / sales if sales > 0 else None
    break_even = fixed_base / contribution_rate if contribution_rate and contribution_rate > 0 else None
    safety = sales - break_even if break_even is not None else None
    return {
        **row,
        "ventas": sales,
        "costos_variables": variable,
        "gastos_fijos": fixed,
        "gastos_fijos_documentados": fixed_documented,
        "base_fija_equilibrio": fixed_base,
        "gastos_totales": variable + fixed,
        "margen_contribucion": contribution,
        "margen_contribucion_pct": contribution_rate,
        "utilidad_operativa": contribution - fixed,
        "punto_equilibrio": break_even,
        "margen_seguridad": safety,
        "margen_seguridad_pct": safety / sales if safety is not None and sales > 0 else None,
        "estado_equilibrio": (
            "sin_ventas" if sales <= 0 else
            "no_calculable" if contribution_rate is None or contribution_rate <= 0 else
            "sobre_equilibrio" if sales >= break_even else "bajo_equilibrio"
        ),
    }


def _provision_period(reference: date, periodicity: str) -> tuple[date, date, int]:
    if periodicity == "semanal":
        start = reference - timedelta(days=reference.weekday())
        return start, start + timedelta(days=6), 1
    if periodicity == "mensual":
        start = reference.replace(day=1)
        end = reference.replace(day=monthrange(reference.year, reference.month)[1])
    elif periodicity == "bimestral":
        first_month = reference.month if reference.month % 2 else reference.month - 1
        start = date(reference.year, first_month, 1)
        end_month = first_month + 1
        end = date(reference.year, end_month, monthrange(reference.year, end_month)[1])
    else:
        start, end = date(reference.year, 1, 1), date(reference.year, 12, 31)
        return start, end, 52
    first_thursday = start + timedelta(days=(3 - start.weekday()) % 7)
    fiscal_weeks = ((end - first_thursday).days // 7) + 1
    return start, end, fiscal_weeks


def _weekly_fixed_provisions(
    conn: Connection, *, week_end: date, sucursal_clave: str | None
) -> list[dict[str, Any]]:
    reference = week_end - timedelta(days=3)  # jueves fiscal de la semana ISO
    rows = conn.execute(
        """
        SELECT DISTINCT ON (p.sucursal_id, p.clave)
               p.id, s.clave AS sucursal_clave, s.nombre AS sucursal,
               p.clave, p.concepto, p.periodicidad, p.importe_periodo,
               p.es_nomina, c.importe_real
        FROM finance.provisiones_fijas p
        JOIN catalog.sucursales s ON s.id = p.sucursal_id
        LEFT JOIN LATERAL (
            SELECT importe_real
            FROM finance.cierres_provision_fija cx
            WHERE cx.provision_id = p.id
              AND %s BETWEEN cx.periodo_desde AND cx.periodo_hasta
            ORDER BY cx.actualizado_en DESC LIMIT 1
        ) c ON true
        WHERE p.activa AND p.vigente_desde <= %s
          AND (%s::text IS NULL OR s.clave = %s)
        ORDER BY p.sucursal_id, p.clave, p.vigente_desde DESC
        """,
        (reference, week_end, sucursal_clave, sucursal_clave),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        period_start, period_end, weeks = _provision_period(reference, item["periodicidad"])
        period_amount = Decimal(
            item["importe_real"] if item["importe_real"] is not None else item["importe_periodo"]
        )
        item.update({
            "periodo_desde": period_start,
            "periodo_hasta": period_end,
            "semanas_periodo": weeks,
            "monto_semanal": (period_amount / weeks).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            "estimado": item["importe_real"] is None,
        })
        result.append(item)
    return result


def _weekly_actual_payroll(
    conn: Connection, *, anio_iso: int, semana_iso: int, sucursal_clave: str | None
) -> list[dict[str, Any]]:
    """Nómina capturada a mano para la semana (una fila por sucursal)."""
    week_start = date.fromisocalendar(anio_iso, semana_iso, 1)
    rows = conn.execute(
        """
        SELECT n.id AS documento_origen_id, s.clave AS sucursal_clave, s.nombre AS sucursal,
               n.monto AS total_documento, n.monto AS monto_aplicado, n.nota
        FROM finance.nomina_semanal n JOIN catalog.sucursales s ON s.id = n.sucursal_id
        WHERE n.anio_iso = %s AND n.semana_iso = %s
          AND (%s::text IS NULL OR s.clave = %s)
        ORDER BY s.clave
        """,
        (anio_iso, semana_iso, sucursal_clave, sucursal_clave),
    ).fetchall()
    return [
        {
            **row,
            "movimiento_id": None,
            "tipo_documento": "nomina_manual",
            "proveedor": "Nómina capturada",
            "fecha": week_start,
            "folio": f"NOMINA-{anio_iso}-S{semana_iso:02d}",
            "categoria": "Nómina",
            "subcategoria": None,
            "pago": row["nota"] or "Captura manual",
            "periodificado": False,
        }
        for row in rows
    ]


def get_payroll_overview(
    conn: Connection, *, anio_iso: int, semana_iso: int, sucursal_clave: str | None
) -> list[dict[str, Any]]:
    """Nómina capturada y provisión estimada por sucursal para una semana ISO."""
    try:
        week_end = date.fromisocalendar(anio_iso, semana_iso, 7)
    except ValueError as exc:
        raise DomainError("La semana ISO indicada no existe.", 422) from exc
    captured = {
        row["sucursal_clave"]: row for row in _weekly_actual_payroll(
            conn, anio_iso=anio_iso, semana_iso=semana_iso, sucursal_clave=sucursal_clave
        )
    }
    estimated: dict[str, Decimal] = {}
    for provision in _weekly_fixed_provisions(conn, week_end=week_end, sucursal_clave=sucursal_clave):
        if provision["es_nomina"]:
            key = provision["sucursal_clave"]
            estimated[key] = estimated.get(key, Decimal("0")) + provision["monto_semanal"]
    branches = conn.execute(
        """
        SELECT clave, nombre FROM catalog.sucursales
        WHERE activa AND clave <> 'POR-ASIGNAR' AND (%s::text IS NULL OR clave = %s)
        ORDER BY clave
        """,
        (sucursal_clave, sucursal_clave),
    ).fetchall()
    return [
        {
            "sucursal_clave": branch["clave"],
            "sucursal": branch["nombre"],
            "estimado": estimated.get(branch["clave"]),
            "capturado": captured[branch["clave"]]["monto_aplicado"] if branch["clave"] in captured else None,
            "nota": captured[branch["clave"]]["nota"] if branch["clave"] in captured else None,
        }
        for branch in branches
    ]


def save_payroll(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    try:
        date.fromisocalendar(data["anio_iso"], data["semana_iso"], 1)
    except ValueError as exc:
        raise DomainError("La semana ISO indicada no existe.", 422) from exc
    branch = conn.execute(
        "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa AND clave <> 'POR-ASIGNAR'",
        (data["sucursal_clave"],),
    ).fetchone()
    if not branch:
        raise DomainError("Sucursal no encontrada o inactiva.", 422)
    if data.get("monto") is None:
        conn.execute(
            "DELETE FROM finance.nomina_semanal WHERE sucursal_id = %s AND anio_iso = %s AND semana_iso = %s",
            (branch["id"], data["anio_iso"], data["semana_iso"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO finance.nomina_semanal (sucursal_id, anio_iso, semana_iso, monto, nota, registrada_por)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sucursal_id, anio_iso, semana_iso) DO UPDATE
            SET monto = EXCLUDED.monto, nota = EXCLUDED.nota,
                registrada_por = EXCLUDED.registrada_por, actualizada_en = now()
            """,
            (branch["id"], data["anio_iso"], data["semana_iso"], data["monto"],
             (data.get("nota") or "").strip() or None, actor),
        )
    return next(
        item for item in get_payroll_overview(
            conn, anio_iso=data["anio_iso"], semana_iso=data["semana_iso"],
            sucursal_clave=data["sucursal_clave"],
        )
    )


def get_weekly_statement(
    conn: Connection,
    *,
    anio_iso: int | None = None,
    semana_iso: int | None = None,
    sucursal_clave: str | None = None,
) -> dict[str, Any]:
    if anio_iso is None or semana_iso is None:
        latest = conn.execute(
            """
            SELECT anio_iso, semana_iso FROM finance.estado_resultados_semanal
            ORDER BY anio_iso DESC, semana_iso DESC LIMIT 1
            """
        ).fetchone()
        if not latest:
            raise DomainError("Todavía no hay ventas o gastos para construir el estado de resultados.", 404)
        anio_iso, semana_iso = latest["anio_iso"], latest["semana_iso"]
    try:
        date.fromisocalendar(anio_iso, semana_iso, 1)
    except ValueError as exc:
        raise DomainError("La semana ISO indicada no existe.", 422) from exc
    week_end = date.fromisocalendar(anio_iso, semana_iso, 7)
    rows = conn.execute(
        """
        SELECT er.*, er.gastos_fijos AS gastos_fijos_documentados,
               pe.gasto_fijo_semanal AS base_fija_equilibrio,
               COALESCE(pe.es_demo, false) AS base_fija_demo
        FROM finance.estado_resultados_semanal er
        LEFT JOIN LATERAL (
            SELECT gasto_fijo_semanal, es_demo
            FROM finance.parametros_equilibrio px
            WHERE px.sucursal_id = er.sucursal_id AND px.vigente_desde <= %s
            ORDER BY px.vigente_desde DESC LIMIT 1
        ) pe ON true
        WHERE er.anio_iso = %s AND er.semana_iso = %s
          AND (%s::text IS NULL OR er.sucursal_clave = %s)
        ORDER BY er.restaurante, er.sucursal
        """,
        (week_end, anio_iso, semana_iso, sucursal_clave, sucursal_clave),
    ).fetchall()
    fixed_provisions = _weekly_fixed_provisions(
        conn, week_end=week_end, sucursal_clave=sucursal_clave
    )
    actual_payroll = _weekly_actual_payroll(
        conn, anio_iso=anio_iso, semana_iso=semana_iso, sucursal_clave=sucursal_clave
    )
    actual_payroll_by_branch = {
        row["sucursal_clave"]: Decimal(row["monto_aplicado"] or 0) for row in actual_payroll
    }
    fixed_nonpayroll_by_branch: dict[str, Decimal] = {}
    estimated_payroll_by_branch: dict[str, Decimal] = {}
    for provision in fixed_provisions:
        key = provision["sucursal_clave"]
        target = estimated_payroll_by_branch if provision["es_nomina"] else fixed_nonpayroll_by_branch
        target[key] = target.get(key, Decimal("0")) + provision["monto_semanal"]
    fixed_by_branch = {
        key: fixed_nonpayroll_by_branch.get(key, Decimal("0"))
             + actual_payroll_by_branch.get(key, estimated_payroll_by_branch.get(key, Decimal("0")))
        for key in set(fixed_nonpayroll_by_branch) | set(estimated_payroll_by_branch) | set(actual_payroll_by_branch)
    }
    detail = [
        _financial_metrics({
            **dict(row),
            "base_fija_equilibrio": fixed_by_branch.get(row["sucursal_clave"], row["base_fija_equilibrio"]),
            "base_fija_demo": False if row["sucursal_clave"] in fixed_by_branch else row["base_fija_demo"],
        })
        for row in rows
    ]
    week_start = date.fromisocalendar(anio_iso, semana_iso, 1)
    commission_detail = weekly_commissions(
        conn, anio_iso=anio_iso, semana_iso=semana_iso, sucursal_clave=sucursal_clave,
        branches={row["sucursal_clave"] for row in rows},
    )
    commissions_by_branch: dict[str, Decimal] = {}
    for item in commission_detail:
        commissions_by_branch[item["sucursal_clave"]] = (
            commissions_by_branch.get(item["sucursal_clave"], Decimal("0")) + item["monto"]
        )
    detail = [
        _financial_metrics({
            **item,
            "costos_variables": item["costos_variables"]
                + commissions_by_branch.get(item["sucursal_clave"], Decimal("0")),
        })
        for item in detail
    ]
    aggregate = {
        "ventas": sum((item["ventas"] for item in detail), Decimal("0")),
        "costos_variables": sum((item["costos_variables"] for item in detail), Decimal("0")),
        "gastos_fijos": sum((item["gastos_fijos"] for item in detail), Decimal("0")),
        "gastos_fijos_documentados": sum((item["gastos_fijos_documentados"] for item in detail), Decimal("0")),
        "base_fija_equilibrio": sum((item["base_fija_equilibrio"] for item in detail), Decimal("0")),
        "ventas_demo": bool(detail) and all(item["ventas_demo"] for item in detail),
        "base_fija_demo": bool(detail) and all(item.get("base_fija_demo", False) for item in detail),
    }
    summary = _financial_metrics(aggregate)
    sales_detail = get_sales_breakdown(
        conn, anio_iso=anio_iso, semana_iso=semana_iso,
        sucursal_clave=sucursal_clave,
    )
    sales_totals = sales_detail["totales"]
    income_breakdown = {
        "efectivo": sales_totals["efectivo"],
        "usd": sales_totals["conversion_usd"],
        "rappi_uber": sales_totals["rappi"] + sales_totals["uber"],
        "tarjeta_credito": sales_totals["credito"],
        "total": sales_totals["monto_neto"],
    }
    expense_rows = conn.execute(
        """
        WITH movimientos AS (
            SELECT m.*,
                   COALESCE(ps.anio_iso, m.anio_iso) AS anio_aplicacion,
                   COALESCE(ps.semana_iso, m.semana_iso) AS semana_aplicacion,
                   COALESCE(ps.monto, m.total) AS total_aplicado
            FROM analytics.movimientos_gasto m
            LEFT JOIN finance.periodificaciones_gasto pg ON
                (m.tipo_documento = 'comprobante_interno' AND pg.comprobante_id = m.documento_origen_id)
                OR (m.tipo_documento <> 'comprobante_interno' AND pg.factura_id = m.documento_origen_id)
            LEFT JOIN finance.periodificacion_semanas ps ON ps.periodificacion_id = pg.id
        )
        SELECT
            CASE mv.categoria_clave
                WHEN 'FIJOS' THEN 'fijos'
                WHEN 'GASTOS_BARRA' THEN 'bar'
                WHEN 'GASTOS_RESTAURANTE' THEN 'restaurante'
                WHEN 'MANTENIMIENTO' THEN 'mantenimiento'
                WHEN 'IMPREVISTOS' THEN 'imprevistos'
                WHEN 'GASOLINA' THEN 'gasolina'
                ELSE 'variables'
            END AS grupo,
            mv.movimiento_id, mv.tipo_documento, mv.documento_origen_id, mv.proveedor,
            mv.fecha, mv.anio_iso AS anio_documento, mv.semana_iso AS semana_documento,
            mv.anio_aplicacion, mv.semana_aplicacion, mv.folio, mv.sucursal_clave, mv.sucursal,
            mv.categoria, mv.subcategoria, mv.total AS total_documento,
            mv.total_aplicado::numeric(14,2) AS monto_aplicado,
            COALESCE(NULLIF(ff.forma_pago, ''), NULLIF(ci.metodo_pago, ''), 'No especificado') AS pago,
            (mv.total_aplicado <> mv.total) AS periodificado
        FROM movimientos mv
        LEFT JOIN core.facturas_finales ff
          ON mv.tipo_documento <> 'comprobante_interno' AND ff.id = mv.movimiento_id
        LEFT JOIN core.comprobantes_internos ci
          ON mv.tipo_documento = 'comprobante_interno' AND ci.id = mv.documento_origen_id
        WHERE mv.anio_aplicacion = %s AND mv.semana_aplicacion = %s
          AND (%s::text IS NULL OR mv.sucursal_clave = %s)
        ORDER BY grupo, fecha, proveedor, folio
        """,
        (anio_iso, semana_iso, sucursal_clave, sucursal_clave),
    ).fetchall()
    expense_map: dict[str, Decimal] = {}
    expense_detail: dict[str, list[dict[str, Any]]] = {}
    for row in expense_rows:
        group = row["grupo"]
        expense_map[group] = expense_map.get(group, Decimal("0")) + Decimal(row["monto_aplicado"] or 0)
        expense_detail.setdefault(group, []).append(dict(row))
    for index, item in enumerate(commission_detail, start=1):
        amount = Decimal(item["monto"])
        expense_map["comisiones"] = expense_map.get("comisiones", Decimal("0")) + amount
        channel = f" {item['canal']}" if item.get("canal") else ""
        expense_detail.setdefault("comisiones", []).append({
            "grupo": "comisiones",
            "movimiento_id": None,
            "tipo_documento": "provision_estimada" if item["estimado"] else "cierre_real",
            "documento_origen_id": None,
            "proveedor": f"{item['concepto']}{channel}",
            "fecha": week_start,
            "anio_documento": anio_iso,
            "semana_documento": semana_iso,
            "anio_aplicacion": anio_iso,
            "semana_aplicacion": semana_iso,
            "folio": f"COMISION-{anio_iso}-S{semana_iso:02d}-{index}",
            "sucursal_clave": item["sucursal_clave"],
            "sucursal": item["sucursal"],
            "categoria": "COMISIONES",
            "subcategoria": item["concepto"],
            "total_documento": amount,
            "monto_aplicado": amount,
            "pago": (
                "Proyección según porcentaje; se sustituye con el cierre real del mes"
                if item["estimado"] else "Importe real de cierre mensual"
            ),
            "periodificado": not item["estimado"],
            "estimado": item["estimado"],
            "base_calculo": item["base"],
            "tasa": item["tasa"],
        })
    expense_map["fijos"] = Decimal("0")
    expense_map["nomina"] = Decimal("0")
    expense_detail["fijos"] = []
    expense_detail["nomina"] = []
    for index, item in enumerate(fixed_provisions, start=1):
        if item["es_nomina"] and item["sucursal_clave"] in actual_payroll_by_branch:
            continue
        group = "nomina" if item["es_nomina"] else "fijos"
        amount = item["monto_semanal"]
        expense_map[group] += amount
        expense_detail[group].append({
            "grupo": group,
            "movimiento_id": None,
            "tipo_documento": "provision_estimada" if item["estimado"] else "cierre_real",
            "documento_origen_id": item["id"],
            "proveedor": item["concepto"],
            "fecha": week_start,
            "anio_documento": anio_iso,
            "semana_documento": semana_iso,
            "anio_aplicacion": anio_iso,
            "semana_aplicacion": semana_iso,
            "folio": f"FIJO-{anio_iso}-S{semana_iso:02d}-{index}",
            "sucursal_clave": item["sucursal_clave"],
            "sucursal": item["sucursal"],
            "categoria": "FIJOS",
            "subcategoria": "NOMINA" if item["es_nomina"] else item["concepto"].upper(),
            "total_documento": item["importe_real"] or item["importe_periodo"],
            "monto_aplicado": amount,
            "pago": "Estimacion provisional sin CFDI" if item["estimado"] else "Importe real de cierre",
            "periodificado": item["semanas_periodo"] > 1,
            "estimado": item["estimado"],
            "periodicidad": item["periodicidad"],
            "semanas_periodo": item["semanas_periodo"],
            "es_nomina": item["es_nomina"],
        })
    for row in actual_payroll:
        amount = Decimal(row["monto_aplicado"] or 0)
        expense_map["nomina"] += amount
        expense_detail["nomina"].append({
            **row,
            "grupo": "nomina",
            "anio_documento": row["fecha"].isocalendar().year,
            "semana_documento": row["fecha"].isocalendar().week,
            "anio_aplicacion": anio_iso,
            "semana_aplicacion": semana_iso,
            "estimado": False,
            "es_nomina": True,
        })
    payroll = expense_map["nomina"]
    estimated_fixed_without_payroll = expense_map["fijos"]
    expense_breakdown = {
        "fijos": estimated_fixed_without_payroll,
        "nomina": payroll,
        "bar": expense_map.get("bar", Decimal("0")),
        "restaurante": expense_map.get("restaurante", Decimal("0")),
        "mantenimiento": expense_map.get("mantenimiento", Decimal("0")),
        "comisiones": expense_map.get("comisiones", Decimal("0")),
        "variables": expense_map.get("variables", Decimal("0")),
        "gasolina": expense_map.get("gasolina", Decimal("0")),
        "imprevistos": expense_map.get("imprevistos", Decimal("0")),
        "total": summary["gastos_totales"],
    }
    food_sales = Decimal(sales_totals.get("venta_alimentos") or 0)
    beverage_sales = Decimal(sales_totals.get("venta_bebidas") or 0)
    visits = int(sales_totals.get("visitas") or 0)
    restaurant_purchases = expense_breakdown["restaurante"]
    bar_purchases = expense_breakdown["bar"]
    labor = expense_breakdown["nomina"]
    purchase_proxy = restaurant_purchases + bar_purchases
    prime_cost_proxy = purchase_proxy + labor
    restaurant_indicators = {
        "margen_operativo": (
            summary["utilidad_operativa"] / summary["ventas"] if summary["ventas"] > 0 else None
        ),
        "compras_alimentos": restaurant_purchases,
        "ventas_alimentos": food_sales,
        "compras_alimentos_pct": restaurant_purchases / food_sales if food_sales > 0 else None,
        "compras_bebidas": bar_purchases,
        "ventas_bebidas": beverage_sales,
        "compras_bebidas_pct": bar_purchases / beverage_sales if beverage_sales > 0 else None,
        "mano_obra": labor,
        "mano_obra_pct": labor / summary["ventas"] if summary["ventas"] > 0 else None,
        "costo_primo_aproximado": prime_cost_proxy,
        "costo_primo_aproximado_pct": (
            prime_cost_proxy / summary["ventas"] if summary["ventas"] > 0 else None
        ),
        "margen_contribucion": summary["margen_contribucion"],
        "margen_contribucion_pct": summary["margen_contribucion_pct"],
        "punto_equilibrio": summary["punto_equilibrio"],
        "visitas": visits,
        "ticket_promedio": summary["ventas"] / visits if visits else None,
        "margen_seguridad": summary["margen_seguridad"],
        "margen_seguridad_pct": summary["margen_seguridad_pct"],
        "metodologia_costos": "compras_aplicadas_sin_ajuste_inventario",
    }
    trend_rows = conn.execute(
        """
        SELECT er.anio_iso, er.semana_iso, sum(er.ventas)::numeric(14,2) AS ventas,
               sum(er.costos_variables)::numeric(14,2) AS costos_variables,
               sum(er.gastos_fijos)::numeric(14,2) AS gastos_fijos_documentados,
               sum(COALESCE(pe.gasto_fijo_semanal, er.gastos_fijos))::numeric(14,2) AS gastos_fijos,
               sum(COALESCE(pe.gasto_fijo_semanal, er.gastos_fijos))::numeric(14,2) AS base_fija_equilibrio
        FROM finance.estado_resultados_semanal er
        LEFT JOIN LATERAL (
            SELECT gasto_fijo_semanal
            FROM finance.parametros_equilibrio px
            WHERE px.sucursal_id = er.sucursal_id
              AND px.vigente_desde <= to_date(
                  er.anio_iso::text || lpad(er.semana_iso::text, 2, '0'), 'IYYYIW'
              ) + 6
            ORDER BY px.vigente_desde DESC LIMIT 1
        ) pe ON true
        WHERE (%s::text IS NULL OR er.sucursal_clave = %s)
          AND (er.anio_iso, er.semana_iso) <= (%s, %s)
        GROUP BY er.anio_iso, er.semana_iso
        ORDER BY anio_iso DESC, semana_iso DESC LIMIT 8
        """,
        (sucursal_clave, sucursal_clave, anio_iso, semana_iso),
    ).fetchall()
    trend = list(reversed([_financial_metrics(dict(row)) for row in trend_rows]))
    return {
        "periodo": {
            "anio_iso": anio_iso,
            "semana_iso": semana_iso,
            "fecha_desde": date.fromisocalendar(anio_iso, semana_iso, 1),
            "fecha_hasta": week_end,
            "sucursal_clave": sucursal_clave,
        },
        "resumen": summary,
        "desglose_ingresos": income_breakdown,
        "desglose_gastos": expense_breakdown,
        "indicadores_restaurante": restaurant_indicators,
        "detalle_gastos": expense_detail,
        "sucursales": detail,
        "tendencia": trend,
    }
