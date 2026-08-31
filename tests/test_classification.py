import pytest

from app.classification import classify_document


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("FACTURA CFDI UUID abc SUBTOTAL 100 IVA 16", "factura_fiscal"),
        ("NOTA DE CRÉDITO CFDI TIPO EGRESO", "nota_credito"),
        ("BANREGIO RECIBO DE LA TRANSFERENCIA CUENTA DESTINO", "transferencia_bancaria"),
        ("BANREGIO TU RECIBO DE PAGO A NATURGY SERVICIO GAS NATURAL", "pago_servicio"),
        ("COMPROBANTE DE PAGO SIPARE IMSS INFONAVIT", "sipare_imss"),
        (
            "CFDI TIPO DE COMPROBANTE P COMPLEMENTO PARA RECEPCION DE PAGOS UUID abc",
            "comprobante_pago",
        ),
        (
            "DOCUMENTOS RELACIONADOS NUM PARCIALIDAD IMPORTE PAGADO SALDO INSOLUTO CFDI",
            "comprobante_pago",
        ),
        ("ESTADO DE CUENTA SALDO PENDIENTE VENCIDO", "desconocido"),
        ("BANCO BBVA NUM. DE CUENTA 123 CLABE: 0123 SWIFT BCMR", "desconocido"),
        ("RECIBO SIMPLE NÚMERO 123", "recibo"),
        ("# DE TICKET 2695 TOTAL 620.40", "ticket_compra"),
        ("NOTA DE VENTA No. 12923 TOTAL 384.00", "nota_venta"),
        ("REMISIÓN No. 0039 BUENO POR 4000", "remision"),
        ("DOCUMENTO SIN INDICADORES", "desconocido"),
    ],
)
def test_document_classification(text, expected):
    result = classify_document(text)
    assert result.type == expected
    assert 0 <= result.confidence <= 1
    assert result.matched_rules
