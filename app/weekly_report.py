from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from psycopg import Connection
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, letter, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.accounting import get_weekly_statement
from app.report_branding import available_logos, get_report_brand


GREEN = colors.HexColor("#176B45")
DARK = colors.HexColor("#12261D")
MINT = colors.HexColor("#E8F3ED")
GOLD = colors.HexColor("#E9B949")
INK = colors.HexColor("#17211C")
MUTED = colors.HexColor("#68746D")
LINE = colors.HexColor("#DFE6E1")
PALE = colors.HexColor("#F6F7F5")
RED = colors.HexColor("#B33A3A")


def _money(value: Any) -> str:
    amount = Decimal(value or 0)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _pct(current: Decimal, previous: Decimal) -> str:
    if previous == 0:
        return "Sin base" if current else "0.0%"
    change = ((current - previous) / previous) * 100
    return f"{change:+.1f}%"


def _previous_week(year: int, week: int) -> tuple[int, int]:
    prior = date.fromisocalendar(year, week, 1).fromordinal(
        date.fromisocalendar(year, week, 1).toordinal() - 7
    )
    iso = prior.isocalendar()
    return iso.year, iso.week


def _purchase_rows(statement: dict[str, Any]) -> list[dict[str, Any]]:
    detail = statement.get("detalle_gastos") or {}
    return [
        {**row, "area_reporte": "Restaurante"}
        for row in detail.get("restaurante", [])
    ] + [
        {**row, "area_reporte": "Barra"}
        for row in detail.get("bar", [])
    ]


def _purchase_totals(statement: dict[str, Any]) -> dict[str, Decimal]:
    expenses = statement.get("desglose_gastos") or {}
    restaurant = Decimal(expenses.get("restaurante") or 0)
    bar = Decimal(expenses.get("bar") or 0)
    return {"restaurante": restaurant, "bar": bar, "total": restaurant + bar}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=27, leading=30, textColor=DARK, alignment=TA_LEFT,
            spaceAfter=1,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=MUTED,
        ),
        "section": ParagraphStyle(
            "ReportSection", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, leading=13, textColor=DARK, spaceBefore=2, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=12, textColor=INK,
        ),
        "small": ParagraphStyle(
            "ReportSmall", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7, leading=9, textColor=MUTED,
        ),
        "metric": ParagraphStyle(
            "ReportMetric", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=15, leading=17, textColor=DARK,
        ),
        "metric_label": ParagraphStyle(
            "ReportMetricLabel", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=10, textColor=MUTED,
        ),
        "right": ParagraphStyle(
            "ReportRight", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8, leading=10, alignment=TA_RIGHT, textColor=INK,
        ),
        "reason_title": ParagraphStyle(
            "PurchaseReasonTitle", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8.2, leading=10, textColor=DARK, spaceAfter=2,
        ),
        "reason_value": ParagraphStyle(
            "PurchaseReasonValue", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=13, leading=15, textColor=INK, spaceAfter=2,
        ),
        "reason_note": ParagraphStyle(
            "PurchaseReasonNote", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.5, leading=8, textColor=MUTED,
        ),
    }


def _page_decorator(brand, branch_key):
    logos = available_logos(branch_key)

    def draw(canvas, doc) -> None:
        canvas.saveState()
        width, height = canvas._pagesize
        canvas.setFillColor(colors.HexColor("#FAFBFA"))
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(brand.primary)
        canvas.rect(0, height - 16 * mm, width, 16 * mm, stroke=0, fill=1)
        x = 15 * mm
        for logo_path in logos:
            image = ImageReader(str(logo_path))
            image_width, image_height = image.getSize()
            max_width = 25 * mm if branch_key else 16 * mm
            max_height = 11 * mm if branch_key else 10 * mm
            scale = min(max_width / image_width, max_height / image_height)
            draw_width, draw_height = image_width * scale, image_height * scale
            canvas.setFillColor(colors.white)
            canvas.roundRect(
                x - 1.5 * mm, height - 14.5 * mm, draw_width + 3 * mm, max_height + 1 * mm,
                1.2 * mm, stroke=0, fill=1,
            )
            canvas.drawImage(
                image, x, height - 14 * mm + (max_height - draw_height) / 2,
                width=draw_width, height=draw_height, mask="auto", preserveAspectRatio=True,
            )
            x += draw_width + 3 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(x + 2 * mm, height - 9.7 * mm, "COMPRAS  /  REPORTE SEMANAL")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 7.5 * mm, "Gestion de compras - cifras aplicadas a la semana actual")
        canvas.drawRightString(width - 15 * mm, 7.5 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    return draw


def _metric_cards(styles, brand, totals, rows, indicators) -> Table:
    items = [
        ("Compras totales", _money(totals["total"])),
        ("Alimentos", _money(totals["restaurante"])),
        ("Bebidas", _money(totals["bar"])),
    ]
    cells = [
        [Paragraph(label.upper(), styles["metric_label"]), Paragraph(value, styles["metric"])]
        for label, value in items
    ]
    table = Table([cells], colWidths=[59.33 * mm] * 3, rowHeights=[19 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (0, 0), brand.pale),
        ("BOX", (0, 0), (-1, -1), .55, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEABOVE", (0, 0), (-1, 0), 2, brand.primary),
    ]))
    return table


def _brand_palette(brand) -> list[colors.Color]:
    def lighten(color, factor):
        return colors.Color(
            color.red + (1 - color.red) * factor,
            color.green + (1 - color.green) * factor,
            color.blue + (1 - color.blue) * factor,
        )
    return [brand.primary, brand.secondary, lighten(brand.secondary, .28), lighten(brand.secondary, .48), lighten(brand.secondary, .66)]


def _area_pie(totals: dict[str, Decimal], brand) -> Drawing:
    restaurant = max(totals["restaurante"], Decimal("0"))
    bar = max(totals["bar"], Decimal("0"))
    values = [restaurant, bar] if restaurant or bar else [Decimal("1"), Decimal("0")]
    drawing = Drawing(245, 132)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 8, 12, 105, 105
    pie.data = [float(value) for value in values]
    pie.labels = None
    palette = _brand_palette(brand)
    pie.slices[0].fillColor = palette[0]
    pie.slices[1].fillColor = palette[1]
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    drawing.add(pie)
    total = restaurant + bar
    restaurant_pct = restaurant / total * 100 if total else Decimal("0")
    bar_pct = bar / total * 100 if total else Decimal("0")
    drawing.add(String(132, 86, "ALIMENTOS", fontName="Helvetica-Bold", fontSize=6.5, fillColor=MUTED))
    drawing.add(String(132, 73, f"{_money(restaurant)}  |  {restaurant_pct:.1f}%", fontName="Helvetica-Bold", fontSize=9, fillColor=palette[0]))
    drawing.add(String(132, 47, "BEBIDAS", fontName="Helvetica-Bold", fontSize=6.5, fillColor=MUTED))
    drawing.add(String(132, 34, f"{_money(bar)}  |  {bar_pct:.1f}%", fontName="Helvetica-Bold", fontSize=9, fillColor=palette[1]))
    return drawing


def _purchase_indicator_cards(styles, totals, rows, indicators) -> Table:
    food_share = totals["restaurante"] / totals["total"] if totals["total"] else Decimal("0")
    items = [
        ("Compras / venta alimentos", _percent_value(indicators.get("compras_alimentos_pct")), "Presion de compra de cocina."),
        ("Compras / venta bebidas", _percent_value(indicators.get("compras_bebidas_pct")), "Presion de compra de barra."),
        ("Participacion alimentos", f"{food_share * 100:.1f}%", "Peso de alimentos en la compra semanal."),
    ]
    cells = []
    for title, value, note in items:
        cells.append(Table([[Paragraph(title, styles["reason_title"])], [Paragraph(value, styles["reason_value"])], [Paragraph(note, styles["reason_note"])]], colWidths=[80 * mm]))
    table = Table([[cell] for cell in cells], colWidths=[85 * mm], rowHeights=[20 * mm] * 3)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _top_provider_chart(rows: list[dict[str, Any]], brand) -> Drawing:
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        totals[row.get("proveedor") or "Sin proveedor"] += Decimal(row.get("monto_aplicado") or 0)
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:5]
    drawing = Drawing(505, 105)
    if not ordered:
        drawing.add(String(8, 52, "Sin compras aplicadas en la semana.", fontName="Helvetica", fontSize=9, fillColor=MUTED))
        return drawing
    maximum = max(amount for _, amount in ordered) or Decimal("1")
    palette = _brand_palette(brand)
    for index, (name, amount) in enumerate(ordered):
        y = 88 - index * 19
        label = name if len(name) <= 28 else name[:27] + "..."
        drawing.add(String(5, y + 2, label, fontName="Helvetica-Bold", fontSize=7, fillColor=INK))
        drawing.add(Rect(145, y, 270, 8, fillColor=colors.HexColor("#E8ECE9"), strokeColor=None))
        drawing.add(Rect(145, y, float(amount / maximum) * 270, 8, fillColor=palette[index], strokeColor=None))
        drawing.add(String(425, y + 1, _money(amount), fontName="Helvetica-Bold", fontSize=7.5, fillColor=INK))
    return drawing


def _history_placeholder(styles, brand) -> Table:
    message = Paragraph(
        "<b>TENDENCIA HISTORICA</b><br/>Conforme se agreguen y cierren nuevas semanas, "
        "el historico mostrara la tendencia de compras para identificar cambios sostenidos.",
        styles["body"],
    )
    table = Table([[message]], colWidths=[177 * mm], rowHeights=[14 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), brand.pale),
        ("BOX", (0, 0), (-1, -1), .7, brand.primary),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return table


def _percent_value(value: Any) -> str:
    return "Sin venta base" if value is None else f"{Decimal(value) * 100:.1f}%"


def _comparison_table(styles, current, previous, average) -> Table:
    data = [["Indicador", "Semana actual", "Semana anterior", "Variacion", "Promedio 4 semanas"]]
    for key, label in (("restaurante", "Restaurante"), ("bar", "Barra"), ("total", "Total")):
        data.append([
            label, _money(current[key]), _money(previous[key]),
            _pct(current[key], previous[key]), _money(average[key]),
        ])
    table = Table(data, colWidths=[52 * mm, 39 * mm, 39 * mm, 31 * mm, 43 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), MINT),
        ("GRID", (0, 0), (-1, -1), .45, LINE),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _trend_chart(weekly: list[tuple[int, int, dict[str, Decimal]]]) -> Drawing:
    drawing = Drawing(660, 118)
    chart = HorizontalLineChart()
    chart.x, chart.y, chart.width, chart.height = 38, 22, 590, 72
    chart.data = [
        [float(item[2]["restaurante"]) for item in weekly],
        [float(item[2]["bar"]) for item in weekly],
    ]
    chart.categoryAxis.categoryNames = [f"S{item[1]}" for item in weekly]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.lines[0].strokeColor = GREEN
    chart.lines[0].strokeWidth = 2
    chart.lines[1].strokeColor = GOLD
    chart.lines[1].strokeWidth = 2
    drawing.add(chart)
    drawing.add(String(43, 106, "Restaurante", fontName="Helvetica-Bold", fontSize=7, fillColor=GREEN))
    drawing.add(String(115, 106, "Barra", fontName="Helvetica-Bold", fontSize=7, fillColor=colors.HexColor("#9A6900")))
    return drawing


def _area_chart(totals: dict[str, Decimal]) -> Drawing:
    drawing = Drawing(270, 155)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 45, 28, 190, 105
    chart.data = [[float(totals["restaurante"]), float(totals["bar"])]]
    chart.categoryAxis.categoryNames = ["Restaurante", "Barra"]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 8
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = GREEN
    chart.bars[0].strokeColor = GREEN
    drawing.add(chart)
    return drawing


def _branch_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"restaurante": Decimal("0"), "bar": Decimal("0"), "docs": 0, "providers": set()}
    )
    for row in rows:
        key = row.get("sucursal") or row.get("sucursal_clave") or "Sin sucursal"
        area = "restaurante" if row["area_reporte"] == "Restaurante" else "bar"
        grouped[key][area] += Decimal(row.get("monto_aplicado") or 0)
        grouped[key]["docs"] += 1
        grouped[key]["providers"].add(row.get("proveedor") or "Sin proveedor")
    output = []
    for name, item in sorted(grouped.items()):
        total = item["restaurante"] + item["bar"]
        output.append([name, _money(item["restaurante"]), _money(item["bar"]), _money(total), item["docs"], len(item["providers"])])
    return output


def _provider_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"restaurante": Decimal("0"), "bar": Decimal("0"), "docs": 0, "branches": set()}
    )
    for row in rows:
        name = row.get("proveedor") or "Sin proveedor"
        area = "restaurante" if row["area_reporte"] == "Restaurante" else "bar"
        grouped[name][area] += Decimal(row.get("monto_aplicado") or 0)
        grouped[name]["docs"] += 1
        grouped[name]["branches"].add(row.get("sucursal") or row.get("sucursal_clave") or "Sin sucursal")
    ordered = sorted(grouped.items(), key=lambda item: item[1]["restaurante"] + item[1]["bar"], reverse=True)
    output = []
    for name, item in ordered:
        total = item["restaurante"] + item["bar"]
        output.append([name, _money(item["restaurante"]), _money(item["bar"]), _money(total), item["docs"], ", ".join(sorted(item["branches"]))])
    return output


def _styled_table(data, widths, *, header=True, font_size=7.5) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), .4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    table.setStyle(TableStyle(commands))
    return table


def _detail_table(rows: list[dict[str, Any]]) -> Table:
    data = [["Proveedor", "Fecha", "Area", "Sucursal", "Monto", "Pago", "Semana", "Factura"]]
    for row in rows:
        data.append([
            str(row.get("proveedor") or "Sin proveedor")[:42],
            row["fecha"].strftime("%d/%m/%Y") if row.get("fecha") else "-",
            row["area_reporte"],
            str(row.get("sucursal") or row.get("sucursal_clave") or "-")[:24],
            _money(row.get("monto_aplicado")),
            str(row.get("pago") or "No especificado")[:18],
            f"S{row.get('semana_aplicacion') or '-'}",
            str(row.get("folio") or "-")[:24],
        ])
    table = _styled_table(
        data, [56 * mm, 22 * mm, 22 * mm, 37 * mm, 26 * mm, 29 * mm, 17 * mm, 38 * mm],
        font_size=6.4,
    )
    table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return table


def build_weekly_purchase_report(
    conn: Connection,
    *,
    anio_iso: int,
    semana_iso: int,
    sucursal_clave: str | None = None,
) -> bytes:
    current_statement = get_weekly_statement(
        conn, anio_iso=anio_iso, semana_iso=semana_iso, sucursal_clave=sucursal_clave
    )
    current = _purchase_totals(current_statement)
    rows = _purchase_rows(current_statement)
    period = current_statement["periodo"]
    indicators = current_statement["indicadores_restaurante"]
    brand = get_report_brand(sucursal_clave)
    styles = _styles()
    styles["title"].textColor = brand.primary
    styles["section"].textColor = brand.primary
    output = BytesIO()
    width, height = A4
    frame = Frame(15 * mm, 13 * mm, width - 30 * mm, height - 31 * mm, id="report")
    doc = BaseDocTemplate(
        output, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=13 * mm,
        title=f"Reporte de compras S{semana_iso} {anio_iso}",
        author="Facturacion IA",
    )
    doc.addPageTemplates(PageTemplate(
        id="weekly", frames=[frame], onPage=_page_decorator(brand, sucursal_clave),
    ))
    scope = brand.name if sucursal_clave else "Consolidado - tres unidades"
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    story = [
        Spacer(1, 2 * mm),
        Paragraph("CIERRE DE COMPRAS  /  SEMANA ACTUAL", styles["small"]),
        Paragraph(scope, styles["title"]),
        Paragraph(
            f"Semana {semana_iso} de {anio_iso} | {period['fecha_desde'].strftime('%d/%m/%Y')} al "
            f"{period['fecha_hasta'].strftime('%d/%m/%Y')}  |  Generado {generated}",
            styles["subtitle"],
        ),
        Spacer(1, 2.5 * mm),
        HRFlowable(width="100%", thickness=.7, color=LINE),
        Spacer(1, 3 * mm),
        _metric_cards(styles, brand, current, rows, indicators),
        Spacer(1, 4 * mm),
        Table([[
            Table([[Paragraph("COMPOSICION DE COMPRAS", styles["section"])], [_area_pie(current, brand)]], colWidths=[89 * mm]),
            Table([[Paragraph("LECTURA DE LA SEMANA", styles["section"])], [_purchase_indicator_cards(styles, current, rows, indicators)]], colWidths=[86 * mm]),
        ]], colWidths=[88.5 * mm, 88.5 * mm], style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
            ("LEFTPADDING", (1, 0), (1, 0), 4),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])),
        Spacer(1, 5 * mm),
        Paragraph("PROVEEDORES CON MAYOR COMPRA", styles["section"]),
        _top_provider_chart(rows, brand),
        Spacer(1, 5 * mm),
        _history_placeholder(styles, brand),
    ]
    doc.build(story)
    return output.getvalue()
