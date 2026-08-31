import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from PIL import Image

from app.errors import DomainError
from app.ocr.base import OcrDocument, OcrLine


MONTHS = {
    "ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "AUG": 8, "BGO": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
}


def _plain(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").upper())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _center(line: OcrLine) -> tuple[float, float]:
    if not line.polygon:
        return 0, 0
    return (
        sum(point[0] for point in line.polygon) / len(line.polygon),
        sum(point[1] for point in line.polygon) / len(line.polygon),
    )


def _money(text: str) -> Decimal | None:
    cleaned = re.sub(r"[^0-9,.-]", "", str(text or ""))
    if not re.search(r"\d", cleaned):
        return None
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("-")
    match = re.search(r"([.,])(\d{2})$", cleaned)
    if match:
        integer = re.sub(r"[^0-9]", "", cleaned[: match.start()]) or "0"
        value = Decimal(f"{integer}.{match.group(2)}")
    else:
        digits = re.sub(r"[^0-9]", "", cleaned)
        value = Decimal(digits or "0")
    return -value if negative else value


def _date_token(text: str, year: int) -> date | None:
    match = re.search(r"\b(\d{1,2})\s*[-/]\s*([A-Za-zÁÉÍÓÚáéíóú]{3,})\b", text)
    if not match:
        return None
    month = MONTHS.get(_plain(match.group(2))[:3])
    if not month:
        return None
    try:
        return date(year, month, int(match.group(1)))
    except ValueError:
        return None


def _nearest_header(x: float, headers: dict[str, float]) -> str:
    return min(headers, key=lambda name: abs(headers[name] - x))


def _line_value_near(
    lines: list[OcrLine], *, y: float, x: float, y_tolerance: float, x_tolerance: float
) -> Decimal:
    candidates = []
    for line in lines:
        cx, cy = _center(line)
        value = _money(line.text)
        if value is not None and abs(cy - y) <= y_tolerance and abs(cx - x) <= x_tolerance:
            candidates.append((abs(cx - x), value))
    return min(candidates, default=(0, Decimal("0")))[1]


def parse_sales_image(document: OcrDocument, image_path: str) -> dict[str, Any]:
    with Image.open(image_path) as image:
        width, height = image.size
    lines = document.lines
    plain_text = _plain(document.text)
    if "EFECTIVO" not in plain_text or "VENTA TOTAL" not in plain_text:
        raise DomainError(
            "La imagen no coincide con el formato semanal: faltan EFECTIVO o VENTA TOTAL.", 422
        )
    year_matches = [int(value) for value in re.findall(r"\b(20\d{2})\b", document.text)]
    year = year_matches[0] if year_matches else datetime.now().year
    week_match = re.search(r"SEMANA\s*(\d{1,2})", plain_text)

    dated_lines = []
    for line in lines:
        parsed = _date_token(line.text, year)
        if parsed:
            x, y = _center(line)
            dated_lines.append((y, x, parsed, line))
    if len(dated_lines) < 7:
        raise DomainError("No fue posible identificar los siete días de la semana.", 422)
    dated_lines.sort(key=lambda item: (item[0], item[1]))
    payment_dates = dated_lines[:7]
    inferred_iso = payment_dates[0][2].isocalendar()
    week = int(week_match.group(1)) if week_match else inferred_iso.week

    header_aliases = {
        "efectivo": ("EFECTIVO",), "dolares": ("DOLARES",),
        "tipo_cambio": ("TIPO DE CAMBIO",), "conversion_usd": ("CONVERSION",),
        "rappi": ("RAPPI", "PLATAFORMAS"), "uber": ("UBER",),
        "visa": ("VISA",), "amex": ("AMEX",), "credito": ("CREDITO",),
        "monto_neto": ("VENTA TOTAL",),
    }
    headers: dict[str, float] = {}
    for field, aliases in header_aliases.items():
        match = next(
            (line for line in lines if any(alias in _plain(line.text) for alias in aliases)),
            None,
        )
        if match:
            headers[field] = _center(match)[0]
    required = {"efectivo", "rappi", "uber", "visa", "amex", "monto_neto"}
    if not required.issubset(headers):
        raise DomainError("No fue posible ubicar todas las columnas del encabezado.", 422)

    rows: list[dict[str, Any]] = []
    for y, _, parsed_date, _ in payment_dates:
        row = {
            "fecha": parsed_date,
            "efectivo": Decimal("0"), "dolares": Decimal("0"),
            "tipo_cambio": Decimal("0"), "rappi": Decimal("0"), "uber": Decimal("0"),
            "visa": Decimal("0"), "amex": Decimal("0"), "monto_neto": Decimal("0"),
            "venta_otro": Decimal("0"), "venta_aplicaciones": Decimal("0"),
            "venta_alimentos": Decimal("0"), "venta_bebidas": Decimal("0"),
            "visitas": 0, "faltante": Decimal("0"), "sobrante": Decimal("0"),
            "total_capturado_manual": False,
        }
        field_candidates: dict[str, list[tuple[float, Decimal]]] = {
            field: [] for field in headers if field in row
        }
        for line in lines:
            cx, cy = _center(line)
            if abs(cy - y) > max(8, height * 0.022) or cx <= width * 0.08:
                continue
            value = _money(line.text)
            if value is None or _plain(line.text).strip() == "$":
                continue
            field = _nearest_header(cx, headers)
            if field in row:
                field_candidates[field].append((abs(cx - headers[field]), value))
        for field, candidates in field_candidates.items():
            if candidates:
                row[field] = min(candidates, key=lambda candidate: candidate[0])[1]
        rows.append(row)

    lower_dates = dated_lines[7:]
    for _, date_x, parsed_date, date_line in lower_dates:
        target = next((row for row in rows if row["fecha"] == parsed_date), None)
        if not target:
            continue
        _, header_y = _center(date_line)
        category_lines = [
            line for line in lines
            if _center(line)[0] < width * 0.08
            and _center(line)[1] > header_y
            and _center(line)[1] < header_y + height * 0.22
        ]
        labels = {
            "OTRO": "venta_otro", "APLICACIONES": "venta_aplicaciones",
            "ALIMENTOS": "venta_alimentos", "BEBIDAS": "venta_bebidas",
        }
        for label, field in labels.items():
            category = next((line for line in category_lines if label in _plain(line.text)), None)
            if category:
                target[field] = _line_value_near(
                    lines, y=_center(category)[1], x=date_x,
                    y_tolerance=max(7, height * 0.018), x_tolerance=max(60, width * 0.06),
                )

    visits_header = next((line for line in lines if "VISITAS" in _plain(line.text)), None)
    if visits_header:
        vx, vy = _center(visits_header)
        visit_values = []
        for line in lines:
            cx, cy = _center(line)
            digits = re.sub(r"[^0-9]", "", line.text)
            if cy > vy and abs(cx - vx) < width * 0.05 and digits:
                number = int(digits)
                if number < 10000:
                    visit_values.append((cy, number))
        visit_values.sort()
        for row, (_, visits) in zip(rows, visit_values[:7]):
            row["visitas"] = visits

    warnings = []
    payment_total = sum((Decimal(row["monto_neto"]) for row in rows), Decimal("0"))
    mix_total = sum(
        (sum((Decimal(row[field]) for field in (
            "venta_otro", "venta_aplicaciones", "venta_alimentos", "venta_bebidas"
        )), Decimal("0")) for row in rows),
        Decimal("0"),
    )
    if abs(payment_total - mix_total) > Decimal("0.02"):
        warnings.append(
            f"El desglose comercial difiere de la venta neta por {payment_total - mix_total:.2f}."
        )
    if inferred_iso.week != week:
        warnings.append(
            f"El encabezado dice semana {week}, pero las fechas corresponden a la {inferred_iso.week}."
        )
    confidence = float(document.confidence or 0)
    if confidence < 0.85:
        warnings.append("La confianza OCR es baja; revise cuidadosamente todos los importes.")
    return {
        "anio_iso": inferred_iso.year,
        "semana_iso": week,
        "filas": rows,
        "confianza_ocr": confidence,
        "proveedor_ocr": document.provider,
        "advertencias": warnings,
        "conciliacion": {
            "venta_neta": payment_total,
            "total_desglose": mix_total,
            "diferencia": mix_total - payment_total,
        },
    }
