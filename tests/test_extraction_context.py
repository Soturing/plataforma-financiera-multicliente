from decimal import Decimal

from app.extraction import extract_invoice_fields
from app.rfc import _check_digit

SUPPLIER = "PRV900101AB" + _check_digit("PRV900101AB")
CLIENT = "CLI010203CD" + _check_digit("CLI010203CD")
OWN = {"own_rfcs": (CLIENT,), "own_names": ("RESTAURANTE EJEMPLO",)}


def invoice_text(**overrides) -> str:
    values = {
        "folio": "FACTURA: F\nREGIMEN FISCAL:\n61754",
        "total": "4,640.00",
        "words": "CUATRO MIL SEISCIENTOS CUARENTA PESOS 00/100 M.N.",
    }
    values.update(overrides)
    return f"""PROVEEDOR EJEMPLO SA DE CV
RESTAURANTE EJEMPLO
CLIENTE: C281
{SUPPLIER}
{CLIENT}
{values['folio']}
FECHA EMISION: 2026-09-15
FECHA VENCIMIENTO: 22/09/2026
SUBTOTAL: 4,000.00
IVA 16%
640.00
TOTAL: {values['total']}
{values['words']}
"""


def test_supplier_rfc_is_never_the_clients_and_name_ignores_own_names():
    result = extract_invoice_fields(invoice_text(), **OWN)

    assert result["rfc_emisor"] == SUPPLIER
    assert result["rfc_receptor"] == CLIENT
    assert result["proveedor_propuesto"] == "PROVEEDOR EJEMPLO SA DE CV"
    assert CLIENT not in result["rfc_candidates"]


def test_folio_is_read_from_a_label_with_the_number_on_a_later_line():
    result = extract_invoice_fields(invoice_text(), **OWN)

    assert result["folio"] == "61754"
    assert result["folio_origen"] == "detectado"


def test_tax_rate_percentage_is_not_read_as_the_iva_amount():
    result = extract_invoice_fields(invoice_text(), **OWN)

    assert result["subtotal"] == Decimal("4000.00")
    assert result["iva"] == Decimal("640.00")
    assert result["total"] == Decimal("4640.00")
    assert result["total_verificado"] is True


def test_amount_in_words_overrides_a_misread_numeric_total():
    result = extract_invoice_fields(invoice_text(total="66,220.00"), **OWN)

    assert result["total"] == Decimal("4640.00")


def test_issue_date_prefers_the_iso_timestamp_over_due_dates():
    result = extract_invoice_fields(
        "FECHA VENCIMIENTO: 30/09/2026\nFecha: 10/02/2026\n2026-09-10T16:15:08\nTOTAL: $100.00"
    )

    assert str(result["fecha_emision"]) == "2026-09-10"


def test_english_month_and_dotted_dates_are_understood():
    assert str(extract_invoice_fields("Fecha Factura 11-September-2026\nTOTAL: $10.00")["fecha_emision"]) == "2026-09-11"
    assert str(extract_invoice_fields("FECHA:15.09.2026\nTOTAL: $10.00")["fecha_emision"]) == "2026-09-15"


def test_sat_qr_overrides_rfc_uuid_and_total():
    qr = {
        "uuid": "123e4567-e89b-42d3-a456-426614174000",
        "emisor_rfc": SUPPLIER,
        "receptor_rfc": CLIENT,
        "total": "4640.00",
    }
    result = extract_invoice_fields("PROVEEDOR EJEMPLO SA DE CV\nTOTAL: 99.00", qr=qr)

    assert result["rfc_emisor"] == SUPPLIER
    assert result["uuid_fiscal"] == qr["uuid"]
    assert result["total"] == Decimal("4640.00")
    assert result["fuente_qr"] is True


def test_certificate_numbers_and_years_are_not_folios():
    result = extract_invoice_fields("FACTURA\n00001000000719545303\n2026\nFECHA: 11/08/2026\nTOTAL: $500.00")

    assert result["folio_origen"] == "fecha"


def test_pac_rfc_in_the_digital_stamp_is_not_the_supplier():
    result = extract_invoice_fields(
        f"PROVEEDOR EJEMPLO SA DE CV\nR.F.C. {SUPPLIER}\nCADENA ORIGINAL DEL COMPLEMENTO\n||1.1|x|2026-01-01|LSO1306189R5|sello||"
    )

    assert result["rfc_emisor"] == SUPPLIER
    assert "LSO1306189R5" not in result["rfc_candidates"]


def test_field_confidence_marks_verified_fields_high_and_guesses_low():
    verified = extract_invoice_fields(invoice_text(), **OWN)["confianza_campos"]

    assert verified["total"]["nivel"] == "alta"
    assert verified["rfc_emisor"]["nivel"] in {"alta", "media"}
    assert verified["folio"]["nivel"] == "alta"
    assert verified["subtotal"]["nivel"] == "alta"

    sparse = extract_invoice_fields("FECHA: 11/08/2026\nTOTAL: $500.00")["confianza_campos"]
    assert sparse["folio"]["nivel"] == "baja"  # se usó la fecha como referencia
    assert sparse["rfc_emisor"]["nivel"] == "baja"
    assert sparse["proveedor_propuesto"]["nivel"] == "baja"
    assert sparse["total"]["nivel"] == "media"  # solo la etiqueta, sin segunda fuente
    assert sparse["fecha_emision"]["nivel"] == "media"  # etiqueta genérica "FECHA"

    with_qr = extract_invoice_fields(
        "TOTAL: $99.00",
        qr={"uuid": "123e4567-e89b-42d3-a456-426614174000", "emisor_rfc": SUPPLIER, "receptor_rfc": CLIENT, "total": "4640.00"},
    )["confianza_campos"]
    assert with_qr["rfc_emisor"]["nivel"] == "alta" and with_qr["total"]["nivel"] == "alta"
