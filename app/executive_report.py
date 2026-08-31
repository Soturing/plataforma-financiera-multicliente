from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any

from psycopg import Connection
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.accounting import get_weekly_statement
from app.report_branding import available_logos, get_report_brand


INK = colors.HexColor("#17211C")
MUTED = colors.HexColor("#66736C")
LINE = colors.HexColor("#DDE4E0")
PALE = colors.HexColor("#F6F8F7")
GREEN = colors.HexColor("#1A7650")
RED = colors.HexColor("#B43A3A")


INDICATOR_GUIDE = [
    (
        "Margen operativo",
        "Utilidad operativa / ventas netas",
        "Mide cuanto queda de cada peso vendido despues de cubrir los costos y gastos operativos. "
        "Permite comparar rentabilidad entre semanas y sucursales, aunque tengan ventas diferentes.",
    ),
    (
        "Compras de alimentos y bebidas",
        "Compras aplicadas / ventas de la familia",
        "Relaciona las compras de cocina y barra con sus ventas correspondientes. En esta etapa es una "
        "senal de abastecimiento; se convertira en costo real cuando se incorporen inventarios y mermas.",
    ),
    (
        "Mano de obra",
        "Nomina documentada / ventas netas",
        "Muestra que proporcion de la venta absorbe el personal. Ayuda a revisar productividad, horarios, "
        "horas extra y dimensionamiento de la plantilla.",
    ),
    (
        "Costo primo aproximado",
        "Compras de alimentos y bebidas + nomina",
        "Agrupa los dos costos operativos mas controlables del restaurante. Si aumenta, conviene revisar "
        "compras, porciones, desperdicio, mezcla de venta y productividad laboral.",
    ),
    (
        "Margen de contribucion",
        "Ventas netas - costos variables",
        "Indica cuanto dejan las ventas para cubrir la estructura fija y producir utilidad. Es especialmente "
        "util para evaluar descuentos, promociones y canales con comision.",
    ),
    (
        "Punto de equilibrio",
        "Gastos fijos / margen de contribucion porcentual",
        "Estima la venta semanal minima necesaria para no perder. Convierte la estructura de costos en una "
        "meta concreta de ventas para cada unidad.",
    ),
    (
        "Ticket promedio",
        "Ventas netas / visitas",
        "Mide el consumo promedio por visita. Debe leerse junto con el numero de visitas para distinguir "
        "crecimiento por trafico, precios o mayor consumo por cliente.",
    ),
    (
        "Margen de seguridad",
        "(Ventas - punto de equilibrio) / ventas",
        "Muestra cuanto pueden caer las ventas antes de entrar en perdida. Un margen reducido indica que la "
        "unidad tiene poco espacio para absorber una semana debil o un gasto inesperado.",
    ),
]


def _money(value: Any) -> str:
    amount = Decimal(value or 0)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _percent(value: Any) -> str:
    return "No disponible" if value is None else f"{Decimal(value) * 100:.1f}%"


def _change(current: Any, previous: Any) -> str:
    current_value = Decimal(current or 0)
    previous_value = Decimal(previous or 0)
    if previous_value == 0:
        return "Sin base comparable"
    return f"{((current_value - previous_value) / abs(previous_value)) * 100:+.1f}%"


def _previous_week(year: int, week: int) -> tuple[int, int]:
    monday = date.fromisocalendar(year, week, 1)
    prior = date.fromordinal(monday.toordinal() - 7).isocalendar()
    return prior.year, prior.week


def _styles(brand) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ExecutiveTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=27, leading=30, textColor=brand.primary, alignment=TA_LEFT,
            spaceAfter=1,
        ),
        "subtitle": ParagraphStyle(
            "ExecutiveSubtitle", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=13, textColor=MUTED,
        ),
        "section": ParagraphStyle(
            "ExecutiveSection", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, leading=13, textColor=brand.primary, spaceBefore=2, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "ExecutiveBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=INK,
        ),
        "small": ParagraphStyle(
            "ExecutiveSmall", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.8, leading=9, textColor=MUTED,
        ),
        "metric": ParagraphStyle(
            "ExecutiveMetric", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=15, leading=17, textColor=brand.primary,
        ),
        "metric_label": ParagraphStyle(
            "ExecutiveMetricLabel", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7, leading=9, textColor=MUTED,
        ),
        "right": ParagraphStyle(
            "ExecutiveRight", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8, leading=10, alignment=TA_RIGHT, textColor=INK,
        ),
        "reason_title": ParagraphStyle(
            "ReasonTitle", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=8.3, leading=10, textColor=brand.primary, spaceAfter=2,
        ),
        "reason_value": ParagraphStyle(
            "ReasonValue", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=12, leading=14, textColor=INK, spaceAfter=2,
        ),
        "reason_note": ParagraphStyle(
            "ReasonNote", parent=base["BodyText"], fontName="Helvetica",
            fontSize=6.5, leading=8, textColor=MUTED,
        ),
    }


def _draw_logo(canvas, path, x, y, max_width, max_height) -> float:
    image = ImageReader(str(path))
    width, height = image.getSize()
    scale = min(max_width / width, max_height / height)
    drawn_width, drawn_height = width * scale, height * scale
    canvas.setFillColor(colors.white)
    canvas.roundRect(
        x - 1.5 * mm, y - .5 * mm, drawn_width + 3 * mm, max_height + 1 * mm,
        1.2 * mm, stroke=0, fill=1,
    )
    canvas.drawImage(
        image, x, y + (max_height - drawn_height) / 2,
        width=drawn_width, height=drawn_height, mask="auto", preserveAspectRatio=True,
    )
    return drawn_width


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
        if branch_key and logos:
            x += _draw_logo(canvas, logos[0], x, height - 14 * mm, 25 * mm, 11 * mm) + 5 * mm
        else:
            for logo in logos:
                x += _draw_logo(canvas, logo, x, height - 14 * mm, 16 * mm, 10 * mm) + 3 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(x, height - 9.7 * mm, "FINANZAS  /  REPORTE SEMANAL")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 6.8)
        canvas.drawString(14 * mm, 7.5 * mm, "Gestion gerencial - cifras estimadas sujetas al cierre mensual")
        canvas.drawRightString(width - 14 * mm, 7.5 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    return draw


def _metric_cards(styles, brand, summary, indicators, prior) -> Table:
    prior_summary = prior["resumen"]
    prior_indicators = prior["indicadores_restaurante"]
    items = [
        ("Ventas netas", _money(summary["ventas"]), _change(summary["ventas"], prior_summary["ventas"])),
        ("Utilidad operativa", _money(summary["utilidad_operativa"]), _change(summary["utilidad_operativa"], prior_summary["utilidad_operativa"])),
        ("Margen operativo", _percent(indicators["margen_operativo"]), f"Anterior: {_percent(prior_indicators['margen_operativo'])}"),
        ("Punto de equilibrio", _money(indicators["punto_equilibrio"]) if indicators["punto_equilibrio"] is not None else "No calculable", f"Ventas: {_money(summary['ventas'])}"),
    ]
    cells = [[
        Paragraph(value, styles["metric"]),
        Paragraph(label, styles["metric_label"]),
        Paragraph(note, styles["small"]),
    ] for label, value, note in items]
    table = Table([cells], colWidths=[58 * mm] * 4, rowHeights=[26 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, brand.primary),
    ]))
    return table


def _statement_table(styles, brand, summary) -> Table:
    rows = [
        ("Ventas netas", summary["ventas"], False),
        ("- Costos variables", summary["costos_variables"], False),
        ("= Margen de contribucion", summary["margen_contribucion"], True),
        ("- Gastos fijos", summary["gastos_fijos"], False),
        ("= Utilidad operativa", summary["utilidad_operativa"], True),
    ]
    data = [[Paragraph(label, styles["body"]), Paragraph(_money(value), styles["right"])] for label, value, _ in rows]
    table = Table(data, colWidths=[76 * mm, 41 * mm])
    commands = [
        ("GRID", (0, 0), (-1, -1), .4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, PALE]),
    ]
    for index, (_, _, emphasized) in enumerate(rows):
        if emphasized:
            commands.extend([
                ("BACKGROUND", (0, index), (-1, index), brand.pale),
                ("FONTNAME", (0, index), (-1, index), "Helvetica-Bold"),
            ])
    table.setStyle(TableStyle(commands))
    return table


def _trend_chart(brand, history) -> Drawing:
    drawing = Drawing(360, 150)
    chart = HorizontalLineChart()
    chart.x, chart.y, chart.width, chart.height = 45, 28, 285, 92
    chart.data = [
        [float(item["resumen"]["ventas"]) for item in history],
        [float(item["resumen"]["utilidad_operativa"]) for item in history],
    ]
    chart.categoryAxis.categoryNames = [f"S{item['periodo']['semana_iso']}" for item in history]
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontSize = 6
    chart.lines[0].strokeColor = brand.primary
    chart.lines[0].strokeWidth = 2
    chart.lines[1].strokeColor = GREEN
    chart.lines[1].strokeWidth = 2
    drawing.add(chart)
    drawing.add(String(48, 136, "Ventas", fontName="Helvetica-Bold", fontSize=7, fillColor=brand.primary))
    drawing.add(String(95, 136, "Utilidad", fontName="Helvetica-Bold", fontSize=7, fillColor=GREEN))
    return drawing


def _indicator_rows(current, prior) -> list[list[Any]]:
    c = current["indicadores_restaurante"]
    p = prior["indicadores_restaurante"]
    values = [
        (_percent(c["margen_operativo"]), _percent(p["margen_operativo"])),
        (f"Alim. {_percent(c['compras_alimentos_pct'])} | Beb. {_percent(c['compras_bebidas_pct'])}", f"Alim. {_percent(p['compras_alimentos_pct'])} | Beb. {_percent(p['compras_bebidas_pct'])}"),
        (_percent(c["mano_obra_pct"]), _percent(p["mano_obra_pct"])),
        (_percent(c["costo_primo_aproximado_pct"]), _percent(p["costo_primo_aproximado_pct"])),
        (_percent(c["margen_contribucion_pct"]), _percent(p["margen_contribucion_pct"])),
        (_money(c["punto_equilibrio"]) if c["punto_equilibrio"] is not None else "No calculable", _money(p["punto_equilibrio"]) if p["punto_equilibrio"] is not None else "No calculable"),
        (_money(c["ticket_promedio"]) if c["ticket_promedio"] is not None else "Sin visitas", _money(p["ticket_promedio"]) if p["ticket_promedio"] is not None else "Sin visitas"),
        (_percent(c["margen_seguridad_pct"]), _percent(p["margen_seguridad_pct"])),
    ]
    return [
        [f"{index}. {name}<br/><font color='#66736C'>{formula}</font>", values[index - 1][0], values[index - 1][1], summary]
        for index, (name, formula, summary) in enumerate(INDICATOR_GUIDE, start=1)
    ]


def _styled_table(data, widths, brand, *, font_size=7.4) -> Table:
    header_style = ParagraphStyle(
        "TableHeader", fontName="Helvetica-Bold", fontSize=font_size,
        leading=font_size + 2, textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "TableCell", fontName="Helvetica", fontSize=font_size,
        leading=font_size + 2.2, textColor=INK,
    )
    wrapped = [
        [Paragraph(str(value), header_style if row_index == 0 else cell_style) for value in row]
        for row_index, row in enumerate(data)
    ]
    table = Table(wrapped, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand.primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), .45, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _branch_rows(statement) -> list[list[Any]]:
    rows = []
    for item in statement["sucursales"]:
        margin = item["utilidad_operativa"] / item["ventas"] if item["ventas"] else None
        rows.append([
            f"{item['restaurante']} - {item['sucursal']}", _money(item["ventas"]),
            _money(item["costos_variables"]), _money(item["gastos_fijos"]),
            _money(item["utilidad_operativa"]), _percent(margin),
            _money(item["punto_equilibrio"]) if item["punto_equilibrio"] is not None else "No calculable",
        ])
    return rows


def _current_metric_cards(styles, brand, summary, indicators) -> Table:
    items = [
        ("Ventas netas", _money(summary["ventas"])),
        ("Utilidad operativa", _money(summary["utilidad_operativa"])),
        ("Margen operativo", _percent(indicators["margen_operativo"])),
        ("Punto de equilibrio", _money(indicators["punto_equilibrio"]) if indicators["punto_equilibrio"] is not None else "No calculable"),
    ]
    cells = [[Paragraph(label.upper(), styles["metric_label"]), Paragraph(value, styles["metric"])] for label, value in items]
    table = Table([cells], colWidths=[44.5 * mm] * 4, rowHeights=[19 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BACKGROUND", (0, 0), (0, 0), brand.pale),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#EDF7F1")),
        ("BOX", (0, 0), (-1, -1), .55, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEABOVE", (0, 0), (-1, 0), 2, brand.primary),
    ]))
    return table


def _current_indicator_table(styles, brand, indicators) -> Table:
    food = _percent(indicators["compras_alimentos_pct"])
    beverages = _percent(indicators["compras_bebidas_pct"])
    items = [
        ("Margen operativo", _percent(indicators["margen_operativo"]), "Rentabilidad final sobre ventas."),
        ("Compras alimentos y bebidas", f"{food}  /  {beverages}", "Alimentos / bebidas sobre su venta."),
        ("Mano de obra", _percent(indicators["mano_obra_pct"]), "Nomina provisional sobre ventas."),
        ("Ticket promedio", _money(indicators["ticket_promedio"]) if indicators["ticket_promedio"] is not None else "Sin visitas", "Venta promedio por visita."),
        ("Punto de equilibrio", _money(indicators["punto_equilibrio"]) if indicators["punto_equilibrio"] is not None else "No calculable", "Meta minima de venta semanal."),
        ("Margen de seguridad", _percent(indicators["margen_seguridad_pct"]), "Colchon antes de entrar en perdida."),
    ]
    cells = []
    for title, value, note in items:
        cells.append(Table([[Paragraph(title, styles["reason_title"])], [Paragraph(value, styles["reason_value"])], [Paragraph(note, styles["reason_note"])]], colWidths=[84 * mm]))
    table = Table([cells[:2], cells[2:4], cells[4:]], colWidths=[88.5 * mm, 88.5 * mm], rowHeights=[22 * mm] * 3)
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


def _compact_statement(styles, brand, summary) -> Table:
    rows = [
        ("Ventas netas", summary["ventas"], brand.primary),
        ("Costos variables", -summary["costos_variables"], INK),
        ("Gastos fijos", -summary["gastos_fijos"], INK),
        ("Utilidad operativa", summary["utilidad_operativa"], GREEN if summary["utilidad_operativa"] >= 0 else RED),
    ]
    data = [[Paragraph(label, styles["body"]), Paragraph(_money(value), styles["right"])] for label, value, _ in rows]
    table = Table(data, colWidths=[51 * mm, 33 * mm], rowHeights=[10.5 * mm] * 4)
    commands = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .5, LINE),
        ("LINEBELOW", (0, 0), (-1, -2), .35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#EDF7F1") if summary["utilidad_operativa"] >= 0 else colors.HexColor("#FBECEC")),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
    ]
    table.setStyle(TableStyle(commands))
    return table


def _composition_pie(brand, summary) -> Drawing:
    variable = max(Decimal(summary["costos_variables"]), Decimal("0"))
    fixed = max(Decimal(summary["gastos_fijos"]), Decimal("0"))
    utility = max(Decimal(summary["utilidad_operativa"]), Decimal("0"))
    values = [variable, fixed, utility]
    if not any(values):
        values = [Decimal("1"), Decimal("0"), Decimal("0")]
    drawing = Drawing(245, 132)
    pie = Pie()
    pie.x, pie.y, pie.width, pie.height = 8, 12, 105, 105
    pie.data = [float(value) for value in values]
    pie.labels = None
    pie.slices[0].fillColor = brand.primary
    pie.slices[1].fillColor = colors.HexColor("#D8A94A")
    pie.slices[2].fillColor = GREEN
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    drawing.add(pie)
    drawing.add(String(132, 93, "COSTOS VARIABLES", fontName="Helvetica-Bold", fontSize=6.5, fillColor=MUTED))
    drawing.add(String(132, 81, _money(variable), fontName="Helvetica-Bold", fontSize=9, fillColor=brand.primary))
    drawing.add(String(132, 60, "GASTOS FIJOS", fontName="Helvetica-Bold", fontSize=6.5, fillColor=MUTED))
    drawing.add(String(132, 48, _money(fixed), fontName="Helvetica-Bold", fontSize=9, fillColor=colors.HexColor("#9A6B12")))
    drawing.add(String(132, 27, "UTILIDAD", fontName="Helvetica-Bold", fontSize=6.5, fillColor=MUTED))
    drawing.add(String(132, 15, _money(summary["utilidad_operativa"]), fontName="Helvetica-Bold", fontSize=9, fillColor=GREEN if summary["utilidad_operativa"] >= 0 else RED))
    return drawing


def build_weekly_executive_report(
    conn: Connection,
    *,
    anio_iso: int,
    semana_iso: int,
    sucursal_clave: str | None = None,
) -> bytes:
    current = get_weekly_statement(conn, anio_iso=anio_iso, semana_iso=semana_iso, sucursal_clave=sucursal_clave)
    brand = get_report_brand(sucursal_clave)
    styles = _styles(brand)
    period = current["periodo"]
    scope = brand.name if sucursal_clave else "Consolidado - tres unidades"
    output = BytesIO()
    width, height = A4
    frame = Frame(15 * mm, 13 * mm, width - 30 * mm, height - 31 * mm, id="executive")
    doc = BaseDocTemplate(
        output, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=13 * mm,
        title=f"Reporte financiero S{semana_iso} {anio_iso}", author="Facturacion IA",
    )
    doc.addPageTemplates(PageTemplate(
        id="executive", frames=[frame], onPage=_page_decorator(brand, sucursal_clave),
    ))

    summary = current["resumen"]
    indicators = current["indicadores_restaurante"]
    story = [
        Spacer(1, 2 * mm),
        Paragraph("CIERRE GERENCIAL  /  SEMANA ACTUAL", styles["small"]),
        Paragraph(scope, styles["title"]),
        Paragraph(
            f"Semana {semana_iso} de {anio_iso} | {period['fecha_desde'].strftime('%d/%m/%Y')} al "
            f"{period['fecha_hasta'].strftime('%d/%m/%Y')}  |  Generado {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            styles["subtitle"],
        ),
        Spacer(1, 2.5 * mm),
        HRFlowable(width="100%", thickness=.7, color=LINE),
        Spacer(1, 3 * mm),
        _current_metric_cards(styles, brand, summary, indicators),
        Spacer(1, 4 * mm),
        Table([[
            Table([[Paragraph("RESULTADO DE LA SEMANA", styles["section"])], [_compact_statement(styles, brand, summary)]], colWidths=[86 * mm]),
            Table([[Paragraph("COMPOSICION OPERATIVA", styles["section"])], [_composition_pie(brand, summary)]], colWidths=[89 * mm]),
        ]], colWidths=[88.5 * mm, 88.5 * mm], style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
            ("LEFTPADDING", (1, 0), (1, 0), 4),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])),
        Spacer(1, 3 * mm),
        Paragraph("RAZONES FINANCIERAS CLAVE", styles["section"]),
        _current_indicator_table(styles, brand, indicators),
    ]
    doc.build(story)
    return output.getvalue()


def build_blank_executive_report(*, sucursal_clave: str | None = None) -> bytes:
    """Build a brand-aware, number-free worksheet for a future weekly close."""
    brand = get_report_brand(sucursal_clave)
    styles = _styles(brand)
    scope = brand.name if sucursal_clave else "Consolidado - tres unidades"
    output = BytesIO()
    width, height = landscape(letter)
    frame = Frame(14 * mm, 14 * mm, width - 28 * mm, height - 35 * mm, id="blank-executive")
    doc = BaseDocTemplate(
        output, pagesize=landscape(letter), leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=18 * mm, bottomMargin=14 * mm,
        title="Plantilla vacia de reporte financiero semanal", author="Facturacion IA",
    )
    doc.addPageTemplates(PageTemplate(
        id="blank-executive", frames=[frame], onPage=_page_decorator(brand, sucursal_clave),
    ))

    blank_cards = [
        ("Ventas netas", "Por capturar"),
        ("Utilidad operativa", "Por capturar"),
        ("Margen operativo", "Por calcular"),
        ("Punto de equilibrio", "Por calcular"),
    ]
    card_cells = [[
        Paragraph(value, styles["metric"]),
        Paragraph(label, styles["metric_label"]),
        Paragraph("Semana sin cerrar", styles["small"]),
    ] for label, value in blank_cards]
    cards = Table([card_cells], colWidths=[58 * mm] * 4, rowHeights=[26 * mm])
    cards.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), .5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, brand.primary),
    ]))

    blank_statement = _styled_table([
        ["Estado de Resultados", "Semana actual", "Semana anterior", "Variacion"],
        ["Ventas netas", "Por capturar", "Por capturar", "Por calcular"],
        ["Costos variables", "Por capturar", "Por capturar", "Por calcular"],
        ["Margen de contribucion", "Por calcular", "Por calcular", "Por calcular"],
        ["Gastos fijos", "Por capturar", "Por capturar", "Por calcular"],
        ["Utilidad operativa", "Por calcular", "Por calcular", "Por calcular"],
    ], [92 * mm, 48 * mm, 48 * mm, 48 * mm], brand)

    blank_reasons = [
        [
            f"{index}. {name}<br/><font color='#66736C'>{formula}</font>",
            "Por calcular", "Por calcular", summary,
        ]
        for index, (name, formula, summary) in enumerate(INDICATOR_GUIDE, start=1)
    ]

    story = [
        Spacer(1, 3 * mm),
        Paragraph("PLANTILLA VACIA - REPORTE FINANCIERO SEMANAL", styles["small"]),
        Paragraph(scope, styles["title"]),
        Paragraph(
            "Semana: ____________________ | Periodo: ______________________________ | "
            "Responsable: ______________________________", styles["subtitle"],
        ),
        Spacer(1, 6 * mm), cards, Spacer(1, 7 * mm),
        Paragraph("Estado de Resultados por completar", styles["section"]),
        blank_statement,
        Spacer(1, 6 * mm),
        Paragraph(
            "Esta plantilla no contiene cifras. Los resultados y razones deben calcularse al cerrar la semana "
            "con las ventas, compras, nomina y gastos documentados.", styles["body"],
        ),
        PageBreak(),
        Spacer(1, 5 * mm),
        Paragraph("Resumen de las 8 razones financieras", styles["section"]),
        Paragraph(
            "Cada razon responde una pregunta distinta. Ninguna debe interpretarse de manera aislada.",
            styles["subtitle"],
        ),
        Spacer(1, 4 * mm),
        _styled_table(
            [["Razon y formula", "Semana actual", "Semana anterior", "Resumen para interpretar"]] + blank_reasons,
            [58 * mm, 39 * mm, 39 * mm, 106 * mm], brand, font_size=6.5,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Nota metodologica", styles["section"]),
        Paragraph(
            "En la primera etapa, alimentos y bebidas usan compras aplicadas y no costo consumido. La segunda "
            "etapa incorporara inventario inicial, inventario final y mermas para calcular costo de ventas.",
            styles["body"],
        ),
        PageBreak(),
        Paragraph("Comparativo por unidad", styles["section"]),
        _styled_table([
            ["Unidad", "Ventas", "Variables", "Fijos", "Utilidad", "Margen op.", "Equilibrio"],
            ["Restaurante Demo Uno", "Por capturar", "Por capturar", "Por capturar", "Por calcular", "Por calcular", "Por calcular"],
            ["Restaurante Demo Tres", "Por capturar", "Por capturar", "Por capturar", "Por calcular", "Por calcular", "Por calcular"],
            ["Restaurante Demo Dos", "Por capturar", "Por capturar", "Por capturar", "Por calcular", "Por calcular", "Por calcular"],
        ], [55 * mm, 31 * mm, 31 * mm, 31 * mm, 31 * mm, 28 * mm, 34 * mm], brand, font_size=6.8),
        Spacer(1, 7 * mm),
        Paragraph("Composicion operativa", styles["section"]),
        _styled_table([
            ["Concepto", "Importe", "% de ventas", "Observaciones"],
            ["Compras de alimentos", "Por capturar", "Por calcular", "________________________________________"],
            ["Compras de bebidas", "Por capturar", "Por calcular", "________________________________________"],
            ["Mano de obra documentada", "Por capturar", "Por calcular", "________________________________________"],
            ["Gastos fijos", "Por capturar", "Por calcular", "________________________________________"],
            ["Utilidad operativa", "Por calcular", "Por calcular", "________________________________________"],
        ], [64 * mm, 40 * mm, 34 * mm, 104 * mm], brand),
    ]
    doc.build(story)
    return output.getvalue()
