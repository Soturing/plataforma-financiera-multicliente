"""Comisiones por sucursal: proyección con porcentajes ajustables y cierre real mensual."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from psycopg import Connection

from app.errors import DomainError
from app.periodification import allocate_period, weeks_for_period

CONCEPTS = {
    "VISA": "Comisión Terminal Visa",
    "AMEX": "Comisión Terminal Amex",
    "BANCO": "Comisión Banco",
    "APPS": "Comisión Apps",
    "SERVICIOS": "Comisión Servicios",
}
BASES = {"visa", "amex", "credito", "uber", "rappi", "ventas_netas", "monto_mensual"}
CHANNELS = {"UBER", "RAPPI"}
CENTS = Decimal("0.01")


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _week_month(week_start: date) -> tuple[int, int]:
    thursday = week_start + timedelta(days=3)
    return thursday.year, thursday.month


def _week_amount_from_month(total: Decimal, week_start: date) -> Decimal:
    """Parte de un importe mensual que corresponde a la semana (el residuo va a la última)."""
    year, month = _week_month(week_start)
    first, last = _month_bounds(year, month)
    iso = week_start.isocalendar()
    for allocation in allocate_period(total, "mensual", first, last):
        if (allocation["anio_iso"], allocation["semana_iso"]) == (iso.year, iso.week):
            return allocation["monto"]
    return Decimal("0")


def list_parameters(conn: Connection, sucursal_clave: str | None = None) -> list[dict[str, Any]]:
    return conn.execute(
        """
        SELECT p.id, s.clave AS sucursal_clave, s.nombre AS sucursal, p.concepto, p.canal,
               p.base, p.porcentaje, p.monto_mensual, p.actualizada_en
        FROM finance.comision_parametros p
        JOIN catalog.sucursales s ON s.id = p.sucursal_id
        WHERE (%s::text IS NULL OR s.clave = %s)
        ORDER BY s.clave, array_position(ARRAY['VISA','AMEX','BANCO','APPS','SERVICIOS'], p.concepto), p.canal
        """,
        (sucursal_clave, sucursal_clave),
    ).fetchall()


def save_parameter(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    concept = str(data["concepto"]).upper()
    channel = (data.get("canal") or None)
    channel = channel.upper() if channel else None
    base = data["base"]
    if concept not in CONCEPTS:
        raise DomainError("Concepto de comisión no válido.", 422)
    if channel and (concept != "APPS" or channel not in CHANNELS):
        raise DomainError("Solo Comisión Apps admite canal (UBER o RAPPI).", 422)
    if base not in BASES:
        raise DomainError("Base de cálculo no válida.", 422)
    percentage, monthly = data.get("porcentaje"), data.get("monto_mensual")
    if base == "monto_mensual":
        if monthly is None:
            raise DomainError("Indique el monto mensual.", 422)
        percentage = None
    else:
        if percentage is None:
            raise DomainError("Indique el porcentaje.", 422)
        monthly = None
    branch = conn.execute(
        "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa", (data["sucursal_clave"],)
    ).fetchone()
    if not branch:
        raise DomainError("Sucursal no encontrada o inactiva.", 422)
    conn.execute(
        """
        INSERT INTO finance.comision_parametros (
            sucursal_id, concepto, canal, base, porcentaje, monto_mensual, actualizada_por
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sucursal_id, concepto, canal) DO UPDATE
        SET base = EXCLUDED.base, porcentaje = EXCLUDED.porcentaje,
            monto_mensual = EXCLUDED.monto_mensual,
            actualizada_por = EXCLUDED.actualizada_por, actualizada_en = now()
        """,
        (branch["id"], concept, channel, base, percentage, monthly, actor),
    )
    return next(
        item for item in list_parameters(conn, data["sucursal_clave"])
        if item["concepto"] == concept and item["canal"] == channel
    )


def delete_parameter(conn: Connection, parameter_id: Any) -> None:
    conn.execute("DELETE FROM finance.comision_parametros WHERE id = %s", (parameter_id,))


def _sales_by_branch(
    conn: Connection, start: date, end: date, sucursal_clave: str | None
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.clave AS sucursal_clave, s.nombre AS sucursal,
               sum(v.visa) AS visa, sum(v.amex) AS amex,
               sum(v.rappi) AS rappi, sum(v.uber) AS uber,
               sum(v.monto_neto) AS ventas_netas
        FROM finance.ventas v JOIN catalog.sucursales s ON s.id = v.sucursal_id
        WHERE v.fecha BETWEEN %s AND %s AND (%s::text IS NULL OR s.clave = %s)
        GROUP BY s.clave, s.nombre
        """,
        (start, end, sucursal_clave, sucursal_clave),
    ).fetchall()
    result = {}
    for row in rows:
        item = {key: Decimal(value or 0) for key, value in row.items() if key not in {"sucursal_clave", "sucursal"}}
        item["credito"] = item["visa"] + item["amex"]
        result[row["sucursal_clave"]] = {**item, "sucursal": row["sucursal"]}
    return result


def _projected_items(
    parameters: list[dict[str, Any]], sales: dict[str, Any] | None, week_start: date
) -> list[dict[str, Any]]:
    items = []
    for param in parameters:
        if param["base"] == "monto_mensual":
            base_amount = Decimal(param["monto_mensual"])
            amount = _week_amount_from_month(base_amount, week_start)
            rate = None
        else:
            base_amount = Decimal((sales or {}).get(param["base"], 0))
            rate = Decimal(param["porcentaje"])
            amount = (base_amount * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
        items.append({
            "concepto_clave": param["concepto"], "concepto": CONCEPTS[param["concepto"]],
            "canal": param["canal"], "base": base_amount, "base_tipo": param["base"],
            "tasa": rate, "monto": amount, "estimado": True,
        })
    return items


def _closings(conn: Connection, year: int, month: int, sucursal_clave: str | None) -> dict[tuple[str, str], Decimal]:
    rows = conn.execute(
        """
        SELECT s.clave AS sucursal_clave, c.concepto, c.importe_real
        FROM finance.comision_cierres c JOIN catalog.sucursales s ON s.id = c.sucursal_id
        WHERE c.anio = %s AND c.mes = %s AND (%s::text IS NULL OR s.clave = %s)
        """,
        (year, month, sucursal_clave, sucursal_clave),
    ).fetchall()
    return {(row["sucursal_clave"], row["concepto"]): Decimal(row["importe_real"]) for row in rows}


def weekly_commissions(
    conn: Connection, *, anio_iso: int, semana_iso: int,
    sucursal_clave: str | None, branches: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Comisiones de la semana: el cierre real del mes sustituye a la proyección."""
    start = date.fromisocalendar(anio_iso, semana_iso, 1)
    end = start + timedelta(days=6)
    year, month = _week_month(start)
    sales = _sales_by_branch(conn, start, end, sucursal_clave)
    closings = _closings(conn, year, month, sucursal_clave)
    names = {
        row["clave"]: row["nombre"] for row in conn.execute(
            "SELECT clave, nombre FROM catalog.sucursales WHERE activa"
        ).fetchall()
    }
    by_branch: dict[str, list[dict[str, Any]]] = {}
    for param in list_parameters(conn, sucursal_clave):
        by_branch.setdefault(param["sucursal_clave"], []).append(param)

    result = []
    for branch in sorted(set(by_branch) | {key for key, _ in closings}):
        if branches is not None and branch not in branches:
            continue
        params = by_branch.get(branch, [])
        for concept in CONCEPTS:
            real = closings.get((branch, concept))
            if real is not None:
                items = [{
                    "concepto_clave": concept, "concepto": CONCEPTS[concept], "canal": None,
                    "base": None, "base_tipo": None, "tasa": None,
                    "monto": _week_amount_from_month(real, start), "estimado": False,
                }]
            else:
                items = _projected_items(
                    [p for p in params if p["concepto"] == concept], sales.get(branch), start
                )
            for item in items:
                if item["monto"]:
                    result.append({**item, "sucursal_clave": branch, "sucursal": names.get(branch, branch)})
    return result


def monthly_summary(
    conn: Connection, *, anio: int, mes: int, sucursal_clave: str | None
) -> list[dict[str, Any]]:
    """Proyectado, real y aplicado por sucursal y concepto para un mes."""
    first, last = _month_bounds(anio, mes)
    weeks = weeks_for_period("mensual", first, last)
    closings = _closings(conn, anio, mes, sucursal_clave)
    params: dict[str, list[dict[str, Any]]] = {}
    for param in list_parameters(conn, sucursal_clave):
        params.setdefault(param["sucursal_clave"], []).append(param)
    names = {
        row["clave"]: row["nombre"] for row in conn.execute(
            "SELECT clave, nombre FROM catalog.sucursales WHERE activa"
        ).fetchall()
    }
    projected: dict[tuple[str, str], Decimal] = {}
    for week in weeks:
        sales = _sales_by_branch(conn, week["fecha_desde"], week["fecha_hasta"], sucursal_clave)
        for branch, branch_params in params.items():
            for item in _projected_items(branch_params, sales.get(branch), week["fecha_desde"]):
                key = (branch, item["concepto_clave"])
                projected[key] = projected.get(key, Decimal("0")) + item["monto"]
    rows = []
    for branch in sorted(set(params) | {key for key, _ in closings}):
        for concept in CONCEPTS:
            estimate = projected.get((branch, concept), Decimal("0"))
            real = closings.get((branch, concept))
            rows.append({
                "sucursal_clave": branch, "sucursal": names.get(branch, branch),
                "concepto": concept, "concepto_nombre": CONCEPTS[concept],
                "proyectado": estimate, "real": real,
                "aplicado": real if real is not None else estimate,
                "diferencia": (real - estimate) if real is not None else None,
            })
    return rows


def save_closing(conn: Connection, data: dict[str, Any], actor: str) -> dict[str, Any]:
    concept = str(data["concepto"]).upper()
    if concept not in CONCEPTS:
        raise DomainError("Concepto de comisión no válido.", 422)
    branch = conn.execute(
        "SELECT id FROM catalog.sucursales WHERE clave = %s AND activa", (data["sucursal_clave"],)
    ).fetchone()
    if not branch:
        raise DomainError("Sucursal no encontrada o inactiva.", 422)
    if data.get("importe_real") is None:
        conn.execute(
            "DELETE FROM finance.comision_cierres WHERE sucursal_id = %s AND concepto = %s AND anio = %s AND mes = %s",
            (branch["id"], concept, data["anio"], data["mes"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO finance.comision_cierres (sucursal_id, concepto, anio, mes, importe_real, actualizado_por)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sucursal_id, concepto, anio, mes) DO UPDATE
            SET importe_real = EXCLUDED.importe_real,
                actualizado_por = EXCLUDED.actualizado_por, actualizado_en = now()
            """,
            (branch["id"], concept, data["anio"], data["mes"], data["importe_real"], actor),
        )
    return next(
        item for item in monthly_summary(
            conn, anio=data["anio"], mes=data["mes"], sucursal_clave=data["sucursal_clave"]
        ) if item["concepto"] == concept
    )
