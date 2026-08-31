from __future__ import annotations

from calendar import monthrange
import json
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.errors import DomainError


PERIOD_TYPES = {"una_semana", "mensual", "bimestral", "personalizado"}


def parse_periodification(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DomainError("La periodificación no tiene un formato JSON válido.", 422) from exc
    if not isinstance(parsed, dict):
        raise DomainError("La periodificación debe ser un objeto.", 422)
    return parsed


def _as_date(value: date | str | None) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise DomainError("La periodificación requiere las fechas de inicio y fin.", 422)
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DomainError("La periodificación contiene una fecha inválida.", 422) from exc


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def weeks_for_period(period_type: str, period_from: date | str, period_to: date | str) -> list[dict[str, Any]]:
    if period_type not in PERIOD_TYPES:
        raise DomainError("Tipo de periodificación no reconocido.", 422)
    start, end = _as_date(period_from), _as_date(period_to)
    if start > end:
        raise DomainError("El inicio del periodo no puede ser posterior al final.", 422)
    if (end - start).days > 370:
        raise DomainError("El periodo no puede abarcar más de un año.", 422)
    if period_type == "mensual" and not (
        start.day == 1 and end == _month_end(start) and (start.year, start.month) == (end.year, end.month)
    ):
        raise DomainError("El periodo mensual debe abarcar un mes calendario completo.", 422)
    if period_type == "bimestral":
        following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if start.day != 1 or end != _month_end(following):
            raise DomainError("El periodo bimestral debe abarcar dos meses calendario consecutivos.", 422)

    if period_type == "una_semana":
        iso = start.isocalendar()
        monday = date.fromisocalendar(iso.year, iso.week, 1)
        return [{
            "anio_iso": iso.year,
            "semana_iso": iso.week,
            "fecha_desde": monday,
            "fecha_hasta": monday + timedelta(days=6),
        }]

    first_monday = start - timedelta(days=start.weekday())
    last_monday = end - timedelta(days=end.weekday())
    weeks = []
    current = first_monday
    while current <= last_monday:
        sunday = current + timedelta(days=6)
        overlap_start, overlap_end = max(current, start), min(sunday, end)
        overlap_days = max(0, (overlap_end - overlap_start).days + 1)
        if overlap_days >= 4:
            iso = current.isocalendar()
            weeks.append({
                "anio_iso": iso.year,
                "semana_iso": iso.week,
                "fecha_desde": current,
                "fecha_hasta": sunday,
            })
        current += timedelta(days=7)
    if not weeks:
        raise DomainError("El periodo no contiene una semana con al menos cuatro días.", 422)
    return weeks


def allocate_period(total: Decimal, period_type: str, period_from: date | str, period_to: date | str) -> list[dict[str, Any]]:
    weeks = weeks_for_period(period_type, period_from, period_to)
    total = Decimal(total).quantize(Decimal("0.01"))
    base = (total / len(weeks)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remaining = total - base * len(weeks)
    return [
        {**week, "monto": base + (remaining if index == len(weeks) - 1 else Decimal("0"))}
        for index, week in enumerate(weeks)
    ]


def save_periodification(
    conn: Connection,
    *,
    invoice_id: UUID | None = None,
    receipt_id: UUID | None = None,
    total: Decimal,
    category_key: str,
    provider_id: UUID,
    subcategory_id: UUID | None,
    config: dict[str, Any] | None,
    actor: str,
    remember: bool = False,
) -> dict[str, Any] | None:
    if config is None:
        return None
    if category_key.upper() != "FIJOS":
        raise DomainError("Solo los gastos de categoría FIJOS pueden periodificarse.", 422)
    if (invoice_id is None) == (receipt_id is None):
        raise ValueError("La periodificación requiere exactamente un documento de origen")
    period_type = str(config.get("tipo") or "")
    period_from = _as_date(config.get("periodo_desde"))
    period_to = _as_date(config.get("periodo_hasta"))
    allocations = allocate_period(total, period_type, period_from, period_to)
    lookup_column, lookup_value = (
        ("factura_id", invoice_id) if invoice_id else ("comprobante_id", receipt_id)
    )
    current = conn.execute(
        f"SELECT id FROM finance.periodificaciones_gasto WHERE {lookup_column} = %s",
        (lookup_value,),
    ).fetchone()
    if current:
        periodification_id = current["id"]
        conn.execute(
            """
            UPDATE finance.periodificaciones_gasto
            SET tipo = %s, periodo_desde = %s, periodo_hasta = %s,
                total_documento = %s, configurada_por = %s, actualizada_en = now()
            WHERE id = %s
            """,
            (period_type, period_from, period_to, total, actor, periodification_id),
        )
        conn.execute(
            "DELETE FROM finance.periodificacion_semanas WHERE periodificacion_id = %s",
            (periodification_id,),
        )
    else:
        periodification_id = conn.execute(
            """
            INSERT INTO finance.periodificaciones_gasto (
                factura_id, comprobante_id, tipo, periodo_desde, periodo_hasta,
                total_documento, configurada_por
            ) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (invoice_id, receipt_id, period_type, period_from, period_to, total, actor),
        ).fetchone()["id"]
    for allocation in allocations:
        conn.execute(
            """
            INSERT INTO finance.periodificacion_semanas (
                periodificacion_id, anio_iso, semana_iso, fecha_desde, fecha_hasta, monto
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                periodification_id, allocation["anio_iso"], allocation["semana_iso"],
                allocation["fecha_desde"], allocation["fecha_hasta"], allocation["monto"],
            ),
        )
    if remember:
        conn.execute(
            """
            INSERT INTO catalog.reglas_periodificacion (
                proveedor_id, subcategoria_id, tipo, activa, aprendida_por
            ) VALUES (%s, %s, %s, true, %s)
            ON CONFLICT (proveedor_id, subcategoria_id)
            DO UPDATE SET tipo = EXCLUDED.tipo, activa = true,
                aprendida_por = EXCLUDED.aprendida_por, actualizada_en = now()
            """,
            (provider_id, subcategory_id, period_type, actor),
        )
    return {
        "id": periodification_id,
        "tipo": period_type,
        "periodo_desde": period_from,
        "periodo_hasta": period_to,
        "semanas": allocations,
    }
