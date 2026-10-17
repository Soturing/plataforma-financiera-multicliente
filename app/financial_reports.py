from __future__ import annotations

from calendar import month_name, monthrange
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Iterable

from psycopg import Connection
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.accounting import get_weekly_statement
from app.errors import DomainError
from app.report_branding import available_logos, get_report_brand


INK = colors.HexColor("#17211C")
MUTED = colors.HexColor("#66736C")
LINE = colors.HexColor("#DDE4E0")
PALE = colors.HexColor("#F6F8F7")
GREEN = colors.HexColor("#1A7650")
RED = colors.HexColor("#B43A3A")
GOLD = colors.HexColor("#C28A24")

MONTHS_ES = (
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

REPORT_SECTIONS = {
    "resumen": ("Resumen ejecutivo", "Indicadores clave y lectura gerencial."),
    "comparacion": ("Comparación mensual", "Mes actual contra el mes anterior."),
    "estado_resultados": ("Estado de resultados", "Ventas, variables, fijos y utilidad."),
    "ventas": ("Ventas", "Canales de cobro, familias, visitas y ticket."),
    "alimentos": ("Alimentos", "Ventas y compras de restaurante por semana."),
    "bebidas": ("Bebidas", "Ventas y compras de barra por semana."),
    "nomina": ("Nómina", "Importe, peso sobre ventas y tendencia."),
    "gastos": ("Gastos fijos y variables", "Composición administrativa y operativa."),
    "punto_equilibrio": ("Punto de equilibrio", "Meta de venta y margen de seguridad."),
    "sucursales": ("Comparativo por sucursal", "Resultados independientes por unidad."),
    "tendencia": ("Tendencia semanal", "Comparación de las semanas elegidas."),
    "movimientos": ("Principales movimientos", "Mayores gastos del periodo para revisión."),
}
DEFAULT_SECTIONS = tuple(REPORT_SECTIONS)


def _decimal(value: Any) -> Decimal:
    return Decimal(value or 0)


def _money(value: Any) -> str:
    amount = _decimal(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _percent(value: Any) -> str:
    return "No disponible" if value is None else f"{_decimal(value) * 100:.1f}%"


def _variation(current: Any, previous: Any) -> Decimal | None:
    current_value = _decimal(current)
    previous_value = _decimal(previous)
    if previous_value == 0:
        return None
    return (current_value - previous_value) / abs(previous_value)


def _variation_label(current: Any, previous: Any) -> str:
    value = _variation(current, previous)
    return "Sin base comparable" if value is None else f"{value * 100:+.1f}%"


def month_iso_periods(year: int, month: int) -> list[tuple[int, int]]:
    """Return ISO weeks with at least four calendar days inside the month."""
    if not 1 <= month <= 12:
        raise DomainError("El mes debe estar entre 1 y 12.", 422)
    counts: dict[tuple[int, int], int] = defaultdict(int)
    for day in range(1, monthrange(year, month)[1] + 1):
        iso = date(year, month, day).isocalendar()
        counts[(iso.year, iso.week)] += 1
    return sorted(period for period, days in counts.items() if days >= 4)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def validate_sections(sections: Iterable[str] | None) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(sections or DEFAULT_SECTIONS))
    invalid = sorted(set(selected) - set(REPORT_SECTIONS))
    if invalid:
        raise DomainError(f"Secciones de reporte no válidas: {', '.join(invalid)}.", 422)
    if not selected:
        raise DomainError("Seleccione al menos una sección para el reporte.", 422)
    return selected


def validate_custom_periods(year: int, weeks: Iterable[int]) -> list[tuple[int, int]]:
    selected = sorted(set(weeks))
    if not selected:
        raise DomainError("Seleccione al menos una semana para comparar.", 422)
    if len(selected) > 16:
        raise DomainError("Seleccione como máximo 16 semanas por reporte.", 422)
    periods = []
    for week in selected:
        try:
            date.fromisocalendar(year, week, 1)
        except ValueError as exc:
            raise DomainError(f"La semana ISO {week} no existe en {year}.", 422) from exc
        periods.append((year, week))
    return periods


def get_report_options(conn: Connection) -> dict[str, Any]:
    periods = [dict(row) for row in conn.execute(
        """
        SELECT DISTINCT anio_iso, semana_iso
        FROM finance.estado_resultados_semanal
        ORDER BY anio_iso DESC, semana_iso DESC
        """
    ).fetchall()]
    branches = [dict(row) for row in conn.execute(
        """
        SELECT clave, restaurante, nombre
        FROM catalog.sucursales
        WHERE activa AND clave <> 'POR-ASIGNAR'
        ORDER BY restaurante, nombre
        """
    ).fetchall()]
    today = date.today()
    latest = periods[0] if periods else {"anio_iso": today.isocalendar().year, "semana_iso": today.isocalendar().week}
    return {
        "periodos": periods,
        "anios": sorted({row["anio_iso"] for row in periods} | {today.year}, reverse=True),
        "sucursales": branches,
        "secciones": [
            {"clave": key, "nombre": name, "descripcion": description, "predeterminada": key in DEFAULT_SECTIONS}
            for key, (name, description) in REPORT_SECTIONS.items()
        ],
        "predeterminado": {
            "anio": today.year,
            "mes": today.month,
            "anio_iso": latest["anio_iso"],
            "semana_iso": latest["semana_iso"],
        },
    }


def _empty_totals() -> dict[str, Decimal]:
    return {
        "ventas": Decimal("0"), "costos_variables": Decimal("0"),
        "gastos_fijos": Decimal("0"), "gastos_totales": Decimal("0"),
        "margen_contribucion": Decimal("0"), "utilidad_operativa": Decimal("0"),
        "efectivo": Decimal("0"), "usd": Decimal("0"),
        "rappi_uber": Decimal("0"), "tarjeta_credito": Decimal("0"),
        "ventas_alimentos": Decimal("0"), "ventas_bebidas": Decimal("0"),
        "compras_alimentos": Decimal("0"), "compras_bebidas": Decimal("0"),
        "nomina": Decimal("0"), "fijos_sin_nomina": Decimal("0"),
        "bar": Decimal("0"), "restaurante": Decimal("0"),
        "mantenimiento": Decimal("0"), "variables": Decimal("0"),
        "gasolina": Decimal("0"), "imprevistos": Decimal("0"),
        "visitas": Decimal("0"),
    }


def _aggregate_statements(
    statements: list[dict[str, Any]], periods: list[tuple[int, int]]
) -> dict[str, Any]:
    totals = _empty_totals()
    branches: dict[str, dict[str, Any]] = {}
    movements: list[dict[str, Any]] = []
    weekly = []
    for statement, (year, week) in zip(statements, periods):
        summary = statement["resumen"]
        income = statement["desglose_ingresos"]
        expenses = statement["desglose_gastos"]
        indicators = statement["indicadores_restaurante"]
        for key in ("ventas", "costos_variables", "gastos_fijos", "gastos_totales", "margen_contribucion", "utilidad_operativa"):
            totals[key] += _decimal(summary[key])
        for key in ("efectivo", "usd", "rappi_uber", "tarjeta_credito"):
            totals[key] += _decimal(income[key])
        totals["ventas_alimentos"] += _decimal(indicators["ventas_alimentos"])
        totals["ventas_bebidas"] += _decimal(indicators["ventas_bebidas"])
        totals["compras_alimentos"] += _decimal(indicators["compras_alimentos"])
        totals["compras_bebidas"] += _decimal(indicators["compras_bebidas"])
        totals["visitas"] += _decimal(indicators["visitas"])
        totals["nomina"] += _decimal(expenses["nomina"])
        totals["fijos_sin_nomina"] += _decimal(expenses["fijos"])
        for key in ("bar", "restaurante", "mantenimiento", "variables", "gasolina", "imprevistos"):
            totals[key] += _decimal(expenses[key])

        weekly.append({
            "anio_iso": year, "semana_iso": week,
            "fecha_desde": statement["periodo"]["fecha_desde"],
            "fecha_hasta": statement["periodo"]["fecha_hasta"],
            "ventas": _decimal(summary["ventas"]),
            "costos_variables": _decimal(summary["costos_variables"]),
            "gastos_fijos": _decimal(summary["gastos_fijos"]),
            "utilidad_operativa": _decimal(summary["utilidad_operativa"]),
            "ventas_alimentos": _decimal(indicators["ventas_alimentos"]),
            "compras_alimentos": _decimal(indicators["compras_alimentos"]),
            "ventas_bebidas": _decimal(indicators["ventas_bebidas"]),
            "compras_bebidas": _decimal(indicators["compras_bebidas"]),
            "nomina": _decimal(expenses["nomina"]),
            "visitas": int(indicators["visitas"] or 0),
        })
        for group, rows in statement["detalle_gastos"].items():
            for row in rows:
                movements.append({**row, "grupo": group})
        for item in statement["sucursales"]:
            key = item["sucursal_clave"]
            current = branches.setdefault(key, {
                "sucursal_clave": key, "restaurante": item["restaurante"],
                "sucursal": item["sucursal"], "ventas": Decimal("0"),
                "costos_variables": Decimal("0"), "gastos_fijos": Decimal("0"),
                "utilidad_operativa": Decimal("0"),
            })
            for metric in ("ventas", "costos_variables", "gastos_fijos", "utilidad_operativa"):
                current[metric] += _decimal(item[metric])

    sales = totals["ventas"]
    contribution_rate = totals["margen_contribucion"] / sales if sales > 0 else None
    break_even = totals["gastos_fijos"] / contribution_rate if contribution_rate and contribution_rate > 0 else None
    safety = sales - break_even if break_even is not None else None
    indicators = {
        "margen_operativo": totals["utilidad_operativa"] / sales if sales > 0 else None,
        "margen_contribucion_pct": contribution_rate,
        "compras_alimentos_pct": totals["compras_alimentos"] / totals["ventas_alimentos"] if totals["ventas_alimentos"] > 0 else None,
        "compras_bebidas_pct": totals["compras_bebidas"] / totals["ventas_bebidas"] if totals["ventas_bebidas"] > 0 else None,
        "nomina_pct": totals["nomina"] / sales if sales > 0 else None,
        "costo_primo": totals["compras_alimentos"] + totals["compras_bebidas"] + totals["nomina"],
        "punto_equilibrio": break_even,
        "margen_seguridad": safety,
        "margen_seguridad_pct": safety / sales if safety is not None and sales > 0 else None,
        "ticket_promedio": sales / totals["visitas"] if totals["visitas"] > 0 else None,
    }
    for item in branches.values():
        item["margen_operativo"] = item["utilidad_operativa"] / item["ventas"] if item["ventas"] else None
    movements.sort(key=lambda row: _decimal(row.get("monto_aplicado")), reverse=True)
    weeks_with_sales = [row for row in weekly if row["ventas"] > 0]
    return {
        "totales": totals,
        "indicadores": indicators,
        "semanas": weekly,
        "cobertura": {
            "semanas_totales": len(weekly),
            "semanas_con_ventas": len(weeks_with_sales),
            "semanas_sin_ventas": [row["semana_iso"] for row in weekly if row["ventas"] <= 0],
            "completa": len(weeks_with_sales) == len(weekly),
        },
        "sucursales": sorted(branches.values(), key=lambda row: row["ventas"], reverse=True),
        "movimientos": movements,
    }


def _load_period(conn: Connection, periods: list[tuple[int, int]], branch: str | None) -> dict[str, Any]:
    statements = [
        get_weekly_statement(conn, anio_iso=year, semana_iso=week, sucursal_clave=branch)
        for year, week in periods
    ]
    return _aggregate_statements(statements, periods)


def build_report_summary(
    conn: Connection,
    *,
    mode: str,
    year: int,
    month: int | None = None,
    weeks: Iterable[int] = (),
    branch: str | None = None,
) -> dict[str, Any]:
    if mode == "mensual":
        if month is None:
            raise DomainError("Indique el mes del reporte.", 422)
        periods = month_iso_periods(year, month)
        previous_year, previous_month_number = previous_month(year, month)
        previous_periods = month_iso_periods(previous_year, previous_month_number)
        title = f"{MONTHS_ES[month].capitalize()} {year}"
        previous_label = f"{MONTHS_ES[previous_month_number].capitalize()} {previous_year}"
    elif mode == "semanas":
        periods = validate_custom_periods(year, weeks)
        previous_periods = []
        title = "Semanas " + ", ".join(f"S{week:02d}" for _, week in periods) + f" de {year}"
        previous_label = None
    else:
        raise DomainError("El tipo de reporte debe ser mensual o por semanas.", 422)

    current = _load_period(conn, periods, branch)
    previous = _load_period(conn, previous_periods, branch) if previous_periods else None
    start = min(date.fromisocalendar(year_value, week, 1) for year_value, week in periods)
    end = max(date.fromisocalendar(year_value, week, 7) for year_value, week in periods)
    return {
        "modo": mode,
        "titulo": title,
        "sucursal_clave": branch,
        "periodo": {
            "fecha_desde": start, "fecha_hasta": end,
            "semanas": [{"anio_iso": y, "semana_iso": w} for y, w in periods],
        },
        "actual": current,
        "comparacion": {
            "etiqueta": previous_label,
            "periodo": [{"anio_iso": y, "semana_iso": w} for y, w in previous_periods],
            "datos": previous,
        } if previous else None,
    }


def _styles(brand) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("MonthlyTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, leading=28, textColor=brand.primary, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("MonthlySubtitle", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED),
        "section": ParagraphStyle("MonthlySection", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=brand.primary, spaceBefore=3, spaceAfter=6),
        "body": ParagraphStyle("MonthlyBody", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=INK),
        "small": ParagraphStyle("MonthlySmall", parent=base["BodyText"], fontName="Helvetica", fontSize=6.8, leading=9, textColor=MUTED),
        "right": ParagraphStyle("MonthlyRight", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, alignment=TA_RIGHT, textColor=INK),
        "metric": ParagraphStyle("MonthlyMetric", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=14, leading=16, textColor=brand.primary),
        "metric_label": ParagraphStyle("MonthlyMetricLabel", parent=base["BodyText"], fontName="Helvetica", fontSize=6.8, leading=8.5, textColor=MUTED),
        "finding": ParagraphStyle("MonthlyFinding", parent=base["BodyText"], fontName="Helvetica", fontSize=8, leading=11, leftIndent=8, bulletIndent=0, textColor=INK, spaceAfter=4),
    }


def _draw_logo(canvas, path, x, y, max_width, max_height) -> float:
    image = ImageReader(str(path))
    width, height = image.getSize()
    scale = min(max_width / width, max_height / height)
    canvas.drawImage(image, x, y, width=width * scale, height=height * scale, preserveAspectRatio=True, mask="auto")
    return width * scale


def _page_decorator(brand, branch):
    logos = available_logos(branch)

    def draw(canvas, doc) -> None:
        canvas.saveState()
        width, height = canvas._pagesize
        canvas.setFillColor(colors.HexColor("#FAFBFA"))
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(brand.primary)
        canvas.rect(0, height - 14 * mm, width, 14 * mm, stroke=0, fill=1)
        x = 14 * mm
        for logo in logos:
            x += _draw_logo(canvas, logo, x, height - 12 * mm, 24 * mm, 9 * mm) + 5 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawRightString(width - 14 * mm, height - 8.5 * mm, "REPORTES FINANCIEROS")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(14 * mm, 7 * mm, "Facturacion IA | Informacion gerencial para uso interno")
        canvas.drawRightString(width - 14 * mm, 7 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    return draw


def _table(data: list[list[Any]], widths: list[float], brand, styles, *, font_size: float = 7.2) -> Table:
    wrapped = []
    for row_index, row in enumerate(data):
        style = ParagraphStyle(
            f"ReportCell{row_index}", parent=styles["body"], fontSize=font_size,
            leading=font_size + 2, textColor=colors.white if row_index == 0 else INK,
            fontName="Helvetica-Bold" if row_index == 0 else "Helvetica",
        )
        wrapped.append([Paragraph(str(value), style) for value in row])
    table = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand.primary),
        ("GRID", (0, 0), (-1, -1), .4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _metric_cards(styles, brand, data: dict[str, Any]) -> Table:
    totals, indicators = data["totales"], data["indicadores"]
    items = [
        ("Ventas netas", _money(totals["ventas"])),
        ("Utilidad operativa", _money(totals["utilidad_operativa"])),
        ("Margen operativo", _percent(indicators["margen_operativo"])),
        ("Punto de equilibrio", _money(indicators["punto_equilibrio"]) if indicators["punto_equilibrio"] is not None else "No calculable"),
    ]
    cells = [[Paragraph(value, styles["metric"]), Paragraph(label.upper(), styles["metric_label"])] for label, value in items]
    table = Table([cells], colWidths=[44.5 * mm] * 4, rowHeights=[21 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .55, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, 0), (-1, 0), 2, brand.primary),
    ]))
    return table


def _findings(data: dict[str, Any], prior: dict[str, Any] | None) -> list[str]:
    totals, indicators = data["totales"], data["indicadores"]
    findings = []
    if prior and data["cobertura"]["completa"] and prior["cobertura"]["completa"]:
        sales_change = _variation(totals["ventas"], prior["totales"]["ventas"])
        profit_change = _variation(totals["utilidad_operativa"], prior["totales"]["utilidad_operativa"])
        if sales_change is not None:
            direction = "crecieron" if sales_change >= 0 else "disminuyeron"
            findings.append(f"Las ventas {direction} {abs(sales_change) * 100:.1f}% frente al periodo anterior.")
        if profit_change is not None:
            direction = "mejoro" if profit_change >= 0 else "se redujo"
            findings.append(f"La utilidad operativa {direction} {abs(profit_change) * 100:.1f}% contra el periodo anterior.")
    elif prior:
        findings.append(
            "La comparacion mensual es preliminar: el periodo actual tiene ventas en "
            f"{data['cobertura']['semanas_con_ventas']} de {data['cobertura']['semanas_totales']} semanas y "
            f"el anterior en {prior['cobertura']['semanas_con_ventas']} de {prior['cobertura']['semanas_totales']}."
        )
    if indicators["margen_operativo"] is not None:
        findings.append(f"El margen operativo fue {_percent(indicators['margen_operativo'])}; cada peso vendido dejo {_money(indicators['margen_operativo'])} antes de impuestos y partidas no operativas.")
    if indicators["nomina_pct"] is not None:
        findings.append(f"La nomina absorbio {_percent(indicators['nomina_pct'])} de las ventas; debe contrastarse con visitas, horarios y productividad por unidad.")
    if indicators["compras_alimentos_pct"] is not None:
        findings.append(f"Las compras de alimentos representaron {_percent(indicators['compras_alimentos_pct'])} de la venta de alimentos; sigue siendo una aproximacion hasta incorporar inventarios y mermas.")
    if indicators["compras_bebidas_pct"] is not None:
        findings.append(f"Las compras de bebidas representaron {_percent(indicators['compras_bebidas_pct'])} de la venta de bebidas.")
    if indicators["margen_seguridad_pct"] is not None:
        findings.append(f"El margen de seguridad fue {_percent(indicators['margen_seguridad_pct'])}: esa es la holgura estimada antes de alcanzar el punto de equilibrio.")
    return findings[:6]


def _trend_chart(brand, weeks: list[dict[str, Any]]) -> Drawing:
    drawing = Drawing(500, 180)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 45, 34, 420, 112
    chart.data = [
        [float(item["ventas"]) for item in weeks],
        [float(item["utilidad_operativa"]) for item in weeks],
    ]
    chart.categoryAxis.categoryNames = [f"S{item['semana_iso']}" for item in weeks]
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontSize = 6
    chart.bars[0].fillColor = brand.primary
    chart.bars[1].fillColor = GREEN
    chart.barWidth = 10
    chart.groupSpacing = 8
    drawing.add(chart)
    drawing.add(String(48, 164, "Ventas", fontName="Helvetica-Bold", fontSize=7, fillColor=brand.primary))
    drawing.add(String(96, 164, "Utilidad", fontName="Helvetica-Bold", fontSize=7, fillColor=GREEN))
    return drawing


def build_configurable_financial_report(
    conn: Connection,
    *,
    mode: str,
    year: int,
    month: int | None = None,
    weeks: Iterable[int] = (),
    branch: str | None = None,
    sections: Iterable[str] | None = None,
) -> bytes:
    selected = validate_sections(sections)
    report = build_report_summary(
        conn, mode=mode, year=year, month=month, weeks=weeks, branch=branch,
    )
    current = report["actual"]
    prior = report["comparacion"]["datos"] if report["comparacion"] else None
    comparison_complete = bool(
        prior and current["cobertura"]["completa"] and prior["cobertura"]["completa"]
    )
    brand = get_report_brand(branch)
    styles = _styles(brand)
    scope = brand.name if branch else "Consolidado - tres unidades"
    period = report["periodo"]
    output = BytesIO()
    width, height = landscape(A4)
    frame = Frame(14 * mm, 13 * mm, width - 28 * mm, height - 31 * mm, id="financial-report")
    doc = BaseDocTemplate(
        output, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=18 * mm, bottomMargin=13 * mm,
        title=f"Reporte financiero {report['titulo']}", author="Facturacion IA",
    )
    doc.addPageTemplates(PageTemplate(
        id="financial-report", frames=[frame], onPage=_page_decorator(brand, branch),
    ))

    story: list[Any] = [
        Spacer(1, 2 * mm),
        Paragraph("REPORTE FINANCIERO GERENCIAL", styles["small"]),
        Paragraph(report["titulo"], styles["title"]),
        Paragraph(
            f"{scope} | {period['fecha_desde'].strftime('%d/%m/%Y')} al {period['fecha_hasta'].strftime('%d/%m/%Y')} | "
            f"Semanas {', '.join(f'S{item['semana_iso']:02d}' for item in period['semanas'])} | "
            f"Generado {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            styles["subtitle"],
        ),
        Spacer(1, 2 * mm), HRFlowable(width="100%", thickness=.7, color=LINE), Spacer(1, 4 * mm),
    ]
    if not current["cobertura"]["completa"]:
        missing = ", ".join(f"S{week:02d}" for week in current["cobertura"]["semanas_sin_ventas"])
        warning = Table([[Paragraph(
            f"CORTE PARCIAL: {missing} no tienen ventas capturadas. El reporte es preliminar y no debe "
            "considerarse cierre mensual hasta completar esas semanas.", styles["body"]
        )]], colWidths=[177 * mm])
        warning.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF7E5")),
            ("BOX", (0, 0), (-1, -1), .6, GOLD),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.extend([warning, Spacer(1, 4 * mm)])

    if "resumen" in selected:
        story.extend([
            _metric_cards(styles, brand, current), Spacer(1, 5 * mm),
            Paragraph("LECTURA PARA LA TOMA DE DECISIONES", styles["section"]),
            *[Paragraph(item, styles["finding"], bulletText="-") for item in _findings(current, prior)],
        ])

    if "comparacion" in selected and prior:
        current_totals, prior_totals = current["totales"], prior["totales"]
        story.extend([
            Spacer(1, 3 * mm), Paragraph(f"COMPARACION CONTRA {report['comparacion']['etiqueta'].upper()}", styles["section"]),
            _table([
                ["Indicador", report["titulo"], report["comparacion"]["etiqueta"], "Variacion"],
                ["Ventas netas", _money(current_totals["ventas"]), _money(prior_totals["ventas"]), _variation_label(current_totals["ventas"], prior_totals["ventas"]) if comparison_complete else "Corte parcial"],
                ["Utilidad operativa", _money(current_totals["utilidad_operativa"]), _money(prior_totals["utilidad_operativa"]), _variation_label(current_totals["utilidad_operativa"], prior_totals["utilidad_operativa"]) if comparison_complete else "Corte parcial"],
                ["Compras alimentos", _money(current_totals["compras_alimentos"]), _money(prior_totals["compras_alimentos"]), _variation_label(current_totals["compras_alimentos"], prior_totals["compras_alimentos"]) if comparison_complete else "Corte parcial"],
                ["Compras bebidas", _money(current_totals["compras_bebidas"]), _money(prior_totals["compras_bebidas"]), _variation_label(current_totals["compras_bebidas"], prior_totals["compras_bebidas"]) if comparison_complete else "Corte parcial"],
                ["Nomina", _money(current_totals["nomina"]), _money(prior_totals["nomina"]), _variation_label(current_totals["nomina"], prior_totals["nomina"]) if comparison_complete else "Corte parcial"],
            ], [73 * mm, 50 * mm, 50 * mm, 45 * mm], brand, styles),
        ])

    if "estado_resultados" in selected:
        totals = current["totales"]
        story.extend([KeepTogether([
            Spacer(1, 7 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 4 * mm),
            Paragraph("ESTADO DE RESULTADOS DEL PERIODO", styles["section"]),
            _table([
                ["Concepto", "Importe", "% de ventas"],
                ["Ventas netas", _money(totals["ventas"]), "100.0%"],
                ["Costos variables", _money(totals["costos_variables"]), _percent(totals["costos_variables"] / totals["ventas"] if totals["ventas"] else None)],
                ["Margen de contribucion", _money(totals["margen_contribucion"]), _percent(current["indicadores"]["margen_contribucion_pct"])],
                ["Gastos fijos, incluida nomina", _money(totals["gastos_fijos"]), _percent(totals["gastos_fijos"] / totals["ventas"] if totals["ventas"] else None)],
                ["Utilidad operativa", _money(totals["utilidad_operativa"]), _percent(current["indicadores"]["margen_operativo"])],
            ], [105 * mm, 58 * mm, 55 * mm], brand, styles, font_size=8),
        ])])

    if "ventas" in selected:
        totals = current["totales"]
        story.extend([
            Spacer(1, 6 * mm), Paragraph("VENTAS POR CANAL Y FAMILIA", styles["section"]),
            _table([
                ["Canal o familia", "Importe", "% de venta"],
                ["Efectivo", _money(totals["efectivo"]), _percent(totals["efectivo"] / totals["ventas"] if totals["ventas"] else None)],
                ["Dolares convertidos", _money(totals["usd"]), _percent(totals["usd"] / totals["ventas"] if totals["ventas"] else None)],
                ["Rappi y Uber", _money(totals["rappi_uber"]), _percent(totals["rappi_uber"] / totals["ventas"] if totals["ventas"] else None)],
                ["Tarjeta de credito", _money(totals["tarjeta_credito"]), _percent(totals["tarjeta_credito"] / totals["ventas"] if totals["ventas"] else None)],
                ["Venta de alimentos", _money(totals["ventas_alimentos"]), _percent(totals["ventas_alimentos"] / totals["ventas"] if totals["ventas"] else None)],
                ["Venta de bebidas", _money(totals["ventas_bebidas"]), _percent(totals["ventas_bebidas"] / totals["ventas"] if totals["ventas"] else None)],
                ["Visitas / ticket promedio", f"{int(totals['visitas']):,}", _money(current["indicadores"]["ticket_promedio"]) if current["indicadores"]["ticket_promedio"] is not None else "No disponible"],
            ], [105 * mm, 58 * mm, 55 * mm], brand, styles),
        ])

    if any(section in selected for section in ("alimentos", "bebidas", "nomina")):
        story.extend([Spacer(1, 7 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 4 * mm)])
    if "alimentos" in selected:
        story.extend([KeepTogether([
            Paragraph("ALIMENTOS - VENTA Y COMPRAS", styles["section"]),
            _table([["Semana", "Venta alimentos", "Compras restaurante", "% compras / venta"]] + [
                [f"S{row['semana_iso']:02d}", _money(row["ventas_alimentos"]), _money(row["compras_alimentos"]), _percent(row["compras_alimentos"] / row["ventas_alimentos"] if row["ventas_alimentos"] else None)]
                for row in current["semanas"]
            ], [42 * mm, 62 * mm, 62 * mm, 52 * mm], brand, styles), Spacer(1, 6 * mm),
        ])])
    if "bebidas" in selected:
        story.extend([KeepTogether([
            Paragraph("BEBIDAS - VENTA Y COMPRAS", styles["section"]),
            _table([["Semana", "Venta bebidas", "Compras barra", "% compras / venta"]] + [
                [f"S{row['semana_iso']:02d}", _money(row["ventas_bebidas"]), _money(row["compras_bebidas"]), _percent(row["compras_bebidas"] / row["ventas_bebidas"] if row["ventas_bebidas"] else None)]
                for row in current["semanas"]
            ], [42 * mm, 62 * mm, 62 * mm, 52 * mm], brand, styles), Spacer(1, 6 * mm),
        ])])
    if "nomina" in selected:
        story.extend([KeepTogether([
            Paragraph("NOMINA Y PRODUCTIVIDAD", styles["section"]),
            _table([["Semana", "Ventas", "Nomina", "Nomina / ventas", "Visitas"]] + [
                [f"S{row['semana_iso']:02d}", _money(row["ventas"]), _money(row["nomina"]), _percent(row["nomina"] / row["ventas"] if row["ventas"] else None), f"{row['visitas']:,}"]
                for row in current["semanas"]
            ], [35 * mm, 52 * mm, 52 * mm, 48 * mm, 31 * mm], brand, styles),
        ])])

    if "gastos" in selected or "punto_equilibrio" in selected:
        story.extend([Spacer(1, 7 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 4 * mm)])
    if "gastos" in selected:
        totals = current["totales"]
        story.extend([KeepTogether([
            Paragraph("COMPOSICION DE GASTOS", styles["section"]),
            _table([
                ["Grupo", "Importe", "% de gastos"],
                ["Nomina", _money(totals["nomina"]), _percent(totals["nomina"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Fijos sin nomina", _money(totals["fijos_sin_nomina"]), _percent(totals["fijos_sin_nomina"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Restaurante", _money(totals["restaurante"]), _percent(totals["restaurante"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Barra", _money(totals["bar"]), _percent(totals["bar"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Mantenimiento", _money(totals["mantenimiento"]), _percent(totals["mantenimiento"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Variables operativos y comisiones", _money(totals["variables"]), _percent(totals["variables"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Gasolina", _money(totals["gasolina"]), _percent(totals["gasolina"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
                ["Imprevistos", _money(totals["imprevistos"]), _percent(totals["imprevistos"] / totals["gastos_totales"] if totals["gastos_totales"] else None)],
            ], [105 * mm, 58 * mm, 55 * mm], brand, styles), Spacer(1, 6 * mm),
        ])])
    if "punto_equilibrio" in selected:
        indicators = current["indicadores"]
        story.extend([KeepTogether([
            Paragraph("PUNTO DE EQUILIBRIO Y SEGURIDAD", styles["section"]),
            _table([
                ["Indicador", "Resultado", "Lectura"],
                ["Margen de contribucion", _percent(indicators["margen_contribucion_pct"]), "Porcion de venta disponible para cubrir estructura fija."],
                ["Punto de equilibrio", _money(indicators["punto_equilibrio"]) if indicators["punto_equilibrio"] is not None else "No calculable", "Venta minima estimada del periodo."],
                ["Margen de seguridad", _money(indicators["margen_seguridad"]) if indicators["margen_seguridad"] is not None else "No calculable", "Holgura monetaria antes de entrar en perdida."],
                ["Margen de seguridad %", _percent(indicators["margen_seguridad_pct"]), "Holgura expresada como porcentaje de ventas."],
            ], [70 * mm, 55 * mm, 93 * mm], brand, styles),
        ])])

    if "sucursales" in selected:
        story.extend([KeepTogether([
            Spacer(1, 7 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 4 * mm),
            Paragraph("COMPARATIVO POR SUCURSAL", styles["section"]),
            _table([["Unidad", "Ventas", "Variables", "Fijos", "Utilidad", "Margen op."]] + [
                [f"{row['restaurante']} - {row['sucursal']}", _money(row["ventas"]), _money(row["costos_variables"]), _money(row["gastos_fijos"]), _money(row["utilidad_operativa"]), _percent(row["margen_operativo"])]
                for row in current["sucursales"]
            ], [64 * mm, 36 * mm, 36 * mm, 36 * mm, 36 * mm, 32 * mm], brand, styles, font_size=6.8),
        ])])
    if "tendencia" in selected:
        story.extend([KeepTogether([
            Spacer(1, 7 * mm), Paragraph("TENDENCIA DE LAS SEMANAS ELEGIDAS", styles["section"]),
            _trend_chart(brand, current["semanas"]),
            _table([["Semana", "Ventas", "Variables", "Fijos", "Utilidad"]] + [
                [f"S{row['semana_iso']:02d}", _money(row["ventas"]), _money(row["costos_variables"]), _money(row["gastos_fijos"]), _money(row["utilidad_operativa"])]
                for row in current["semanas"]
            ], [40 * mm, 52 * mm, 52 * mm, 52 * mm, 52 * mm], brand, styles),
        ])])

    if "movimientos" in selected:
        top = current["movimientos"][:16]
        story.extend([KeepTogether([
            Spacer(1, 7 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 4 * mm),
            Paragraph("PRINCIPALES MOVIMIENTOS DE GASTO", styles["section"]),
            Paragraph("Ordenados por monto aplicado. Para auditoria documental completa utilice el Reporte para Compras.", styles["subtitle"]),
            Spacer(1, 3 * mm),
            _table([["Grupo", "Proveedor", "Fecha", "Sucursal", "Folio", "Monto aplicado"]] + [
                [row.get("grupo", ""), row.get("proveedor", "Sin proveedor"), row.get("fecha", ""), row.get("sucursal", row.get("sucursal_clave", "")), row.get("folio", ""), _money(row.get("monto_aplicado"))]
                for row in top
            ], [31 * mm, 62 * mm, 29 * mm, 45 * mm, 42 * mm, 39 * mm], brand, styles, font_size=6.2),
        ])])

    story.extend([
        Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=.5, color=LINE), Spacer(1, 2 * mm),
        Paragraph(
            "Nota metodologica: alimentos y bebidas representan compras aplicadas, no costo consumido. "
            "El costo real requerira inventario inicial, inventario final y mermas. Las cifras de nomina y "
            "gastos fijos pueden incluir provisiones cuando aun no existe un cierre real.",
            styles["small"],
        ),
    ])
    doc.build(story)
    return output.getvalue()
