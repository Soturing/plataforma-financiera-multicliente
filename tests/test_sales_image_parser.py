from datetime import date
from decimal import Decimal

import pytest
from PIL import Image

from app.ocr.base import OcrDocument, OcrLine
from app.sales_image import parse_sales_image


def line(text, x, y):
    return OcrLine(text=text, confidence=0.98, polygon=[[x - 20, y - 6], [x + 20, y - 6], [x + 20, y + 6], [x - 20, y + 6]])


@pytest.mark.parametrize("rappi_header", ["RAPPI", "PLATAFORMAS"])
def test_sales_image_parser_reconstructs_columns_and_two_date_blocks(tmp_path, rappi_header):
    image_path = tmp_path / "ventas.png"
    Image.new("RGB", (1280, 410), "white").save(image_path)
    headers = {
        "EFECTIVO": 165, "DOLARES": 275, "TIPO DE CAMBIO": 375,
        "CONVERSION": 477, rappi_header: 576, "UBER": 674, "VISA": 806,
        "AMEX": 968, "CREDITO": 1098, "VENTA TOTAL": 1200,
    }
    lines = [line("SEMANA 30", 80, 12), line("2026", 1235, 12)]
    lines.extend(line(label, x, 30) for label, x in headers.items())
    dates = [date(2026, 7, day) for day in range(20, 27)]
    sales = [100, 200, 300, 400, 500, 600, 700]
    for index, (day, total) in enumerate(zip(dates, sales)):
        y = 50 + index * 18
        lines.extend([
            line(day.strftime("%d-Jul"), 80, y),
            line(f"{total:.2f}", headers["EFECTIVO"], y),
            line("12.50", headers[rappi_header], y),
            line(f"{total:.2f}", headers["VENTA TOTAL"], y),
        ])
    category_y = {"OTRO": 246, "APLICACIONES": 262, "ALIMENTOS": 278, "BEBIDAS": 294}
    for index, day in enumerate(dates[:4]):
        x = 165 + index * 105
        lines.append(line(day.strftime("%d-Jul"), x, 230))
        lines.extend(line(label, 35, y) for label, y in category_y.items())
        lines.extend([
            line("10.00", x, category_y["OTRO"]),
            line("20.00", x, category_y["APLICACIONES"]),
            line(f"{sales[index] - 60:.2f}", x, category_y["ALIMENTOS"]),
            line("30.00", x, category_y["BEBIDAS"]),
        ])
    second_y = {"OTRO": 340, "APLICACIONES": 356, "ALIMENTOS": 372, "BEBIDAS": 388}
    for relative, day in enumerate(dates[4:]):
        index = relative + 4
        x = 165 + relative * 105
        lines.append(line(day.strftime("%d-Jul"), x, 325))
        lines.extend(line(label, 35, y) for label, y in second_y.items())
        lines.extend([
            line("10.00", x, second_y["OTRO"]),
            line("20.00", x, second_y["APLICACIONES"]),
            line(f"{sales[index] - 60:.2f}", x, second_y["ALIMENTOS"]),
            line("30.00", x, second_y["BEBIDAS"]),
        ])
    lines.append(line("VISITAS", 1100, 230))
    for index, y in enumerate([246, 262, 278, 294, 325, 340, 356], start=1):
        lines.append(line(str(index * 10), 1100, y))
    document = OcrDocument(
        text="\n".join(item.text for item in lines), lines=lines, confidence=0.98,
        raw={}, provider="pytest-ocr", model="synthetic", duration_ms=1,
    )

    parsed = parse_sales_image(document, str(image_path))

    assert parsed["anio_iso"] == 2026
    assert parsed["semana_iso"] == 30
    assert len(parsed["filas"]) == 7
    assert parsed["conciliacion"]["venta_neta"] == Decimal("2800.00")
    assert parsed["conciliacion"]["total_desglose"] == Decimal("2800.00")
    assert parsed["conciliacion"]["diferencia"] == Decimal("0.00")
    assert [row["rappi"] for row in parsed["filas"]] == [Decimal("12.50")] * 7
    assert [row["visitas"] for row in parsed["filas"]] == [10, 20, 30, 40, 50, 60, 70]


def test_sales_image_parser_tolerates_august_ocr_and_currency_noise(tmp_path):
    image_path = tmp_path / "ventas-agosto.png"
    Image.new("RGB", (1320, 420), "white").save(image_path)
    headers = {
        "EFECTIVO": 166, "DOLARES": 280, "TIPO DE CAMBIO": 386,
        "CONVERSION": 494, "PLATAFORMAS": 598, "UBER": 703,
        "VISA": 842, "AMEX": 1014, "TARJETA DE CREDITO": 1150,
        "VENTA TOTAL": 1258,
    }
    lines = [line(label, x, 8) for label, x in headers.items()]
    for index, day in enumerate(range(3, 10)):
        y = 27 + index * 18
        date_text = "09-Bgo" if day == 9 else f"{day:02d}-ago"
        lines.extend([
            line(date_text, 87, y),
            line("5", 762, y),
            line("15608.00", 724, y),
            line("100.00", headers["EFECTIVO"] + 34, y),
            line("20.00", headers["PLATAFORMAS"] + 25, y),
            line("200.00", headers["VISA"] + 58, y),
            line("30.00", headers["AMEX"] + 59, y),
            line("15958.00", headers["VENTA TOTAL"] + 28, y),
        ])
    document = OcrDocument(
        text="\n".join(item.text for item in lines), lines=lines, confidence=0.84,
        raw={}, provider="pytest-ocr", model="synthetic", duration_ms=1,
    )

    parsed = parse_sales_image(document, str(image_path))

    assert parsed["semana_iso"] == 32
    assert len(parsed["filas"]) == 7
    assert parsed["filas"][-1]["fecha"] == date(2026, 8, 9)
    assert [row["uber"] for row in parsed["filas"]] == [Decimal("15608.00")] * 7
