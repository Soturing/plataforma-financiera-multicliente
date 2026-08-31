from decimal import Decimal

from app.extraction import extract_invoice_fields


def test_extracts_core_mexican_invoice_fields():
    result = extract_invoice_fields(
        """
        PROVEEDOR: Proveedor Ficticio Uno SA de CV
        RFC: PDA010101AA1
        FECHA: 07/08/2026
        UUID: 123e4567-e89b-12d3-a456-426614174000
        SUBTOTAL: $10,000.00
        IVA: $1,600.00
        TOTAL: $11,600.00
        """
    )
    assert result["proveedor_propuesto"] == "Proveedor Ficticio Uno SA de CV"
    assert result["rfc_emisor"] == "PDA010101AA1"
    assert str(result["fecha_emision"]) == "2026-08-07"
    assert result["subtotal"] == Decimal("10000.00")
    assert result["iva"] == Decimal("1600.00")
    assert result["total"] == Decimal("11600.00")


def test_generic_customer_rfc_never_replaces_supplier_rfc():
    result = extract_invoice_fields(
        """
        PROVEEDOR FICTICIO GAMMA
        RFC: DEMO010101AA1
        CLIENTE: RESTAURANTE DEMO DOS
        RFC: XAXX010101000
        TOTAL: $2,963.27
        """
    )

    assert result["rfc_emisor"] == "DEMO010101AA1"
    assert result["rfc_candidates"] == ["DEMO010101AA1"]


def test_generic_rfc_alone_is_not_a_provider_identifier():
    result = extract_invoice_fields("RFC: XAXX010101000\nTOTAL: $500.00")

    assert result["rfc_emisor"] is None
    assert result["rfc_candidates"] == []


def test_zero_total_is_left_pending_for_human_review():
    result = extract_invoice_fields("SUBTOTAL: $5,097.00\nIVA: $0.00\nTOTAL: $0.00")

    assert result["total"] is None


def test_extracts_split_total_and_spanish_date():
    result = extract_invoice_fields(
        """
        FECHA:
        17 junio 2026
        $30,500.75 pesos
        TOTAL A PAGAR:
        """
    )
    assert str(result["fecha_emision"]) == "2026-06-17"
    assert result["total"] == Decimal("30500.75")


def test_extracts_iso_emission_date_without_treating_year_as_day():
    result = extract_invoice_fields(
        """
        FECHA DE EMISIÓN: 2026-08-05T16:04:33
        SUBTOTAL: $1,000.00
        TOTAL: $1,160.00
        """
    )

    assert str(result["fecha_emision"]) == "2026-08-05"


def test_extracts_abbreviated_spanish_date_and_hyphenated_subtotal():
    result = extract_invoice_fields(
        """
        FECHA Y HORA DE EMISIÓN DE CFDI:
        03/ago./2026 - 15:28:05
        65,000.00
        0.00
        65,000.00
        SUB-TOTAL
        I.V.A.
        TOTAL
        """
    )

    assert str(result["fecha_emision"]) == "2026-08-03"
    assert result["subtotal"] == Decimal("65000.00")
    assert result["total"] == Decimal("65000.00")


def test_prefers_invoice_total_over_zero_balance_due():
    result = extract_invoice_fields(
        """
        Subtotal
        MXN $
        4,000.00
        IVA 16%
        MXN $
        640.00
        Total
        MXN $
        4,640.00
        Cantidad por pagar
        MXN $
        0.00
        Importe total con letra
        """
    )

    assert result["subtotal"] == Decimal("4000.00")
    assert result["total"] == Decimal("4640.00")


def test_extracts_invoice_note_and_ticket_numbers():
    invoice = extract_invoice_fields("FECHA: 11/08/2026\nFactura No: A-92831")
    note = extract_invoice_fields("FECHA: 11/08/2026\nNÚMERO DE NOTA: NV/443-2")
    ticket = extract_invoice_fields("FECHA: 11/08/2026\nTICKET # 009871")

    assert invoice["folio"] == "A-92831"
    assert note["folio"] == "NV/443-2"
    assert ticket["folio"] == "009871"
    assert invoice["folio_origen"] == "detectado"


def test_uses_ddmmyyyy_when_document_has_no_number():
    result = extract_invoice_fields("FECHA DE EMISIÓN: 11/08/2026\nTOTAL: $500.00")

    assert result["folio"] == "11082026"
    assert result["folio_origen"] == "fecha"


def test_does_not_use_fiscal_uuid_as_invoice_number():
    result = extract_invoice_fields(
        "FECHA: 11/08/2026\nFOLIO FISCAL: 123e4567-e89b-12d3-a456-426614174000"
    )

    assert result["folio"] == "11082026"


def test_extracts_remission_with_split_short_date_and_integer_total():
    result = extract_invoice_fields(
        """
        REMISIÓN
        PROVEEDOR FICTICIO DELTAE EQUIPO
        No.
        0039
        FECHA
        10
        8
        26
        BUENO POR $ 4000
        """
    )

    assert result["proveedor_propuesto"] == "PROVEEDOR FICTICIO DELTAE EQUIPO"
    assert result["folio"] == "0039"
    assert str(result["fecha_emision"]) == "2026-08-10"
    assert result["total"] == Decimal("4000.00")


def test_extracts_generic_receipt_without_inventing_numeric_provider():
    result = extract_invoice_fields(
        """
        RECIBO DE DINERO
        FECHA
        10
        08
        26
        LA CANTIDAD DE
        1.loo
        CONCEPTO
        PAGO EN EFECTIVO
        BUENO POR $ 1100
        """
    )

    assert result["proveedor_propuesto"] is None
    assert result["folio"] == "10082026"
    assert result["folio_origen"] == "fecha"
    assert result["total"] == Decimal("1100.00")


def test_extracts_ticket_and_sale_note_references_and_totals():
    ticket = extract_invoice_fields(
        "# DE TICKET\n0000002695\n10/Ago/26\nTOTAL\n620.40"
    )
    sale_note = extract_invoice_fields(
        "NOTA DE VENTA\nNo.\n12923\nTOTAL $384"
    )

    assert ticket["folio"] == "0000002695"
    assert str(ticket["fecha_emision"]) == "2026-08-10"
    assert ticket["total"] == Decimal("620.40")
    assert sale_note["folio"] == "12923"
    assert sale_note["total"] == Decimal("384.00")
