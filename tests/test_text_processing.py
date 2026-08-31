from pathlib import Path

import fitz

from app.ocr.base import OcrDocument
from app.ocr.paddle_engine import PaddleOcrEngine
from app.text_processing import HybridTextEngine
from app.extraction import extract_invoice_fields


def make_pdf(path: Path, texts: list[str]) -> None:
    document = fitz.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class FakeOcrEngine:
    def read(self, path: str) -> OcrDocument:
        return OcrDocument(
            text="texto obtenido por OCR",
            lines=[],
            confidence=0.9,
            raw={"source": "fake_ocr"},
            provider="fake-ocr",
            model="test",
            duration_ms=1,
        )


def test_native_pdf_text_avoids_ocr_and_preserves_all_pages(tmp_path):
    source = tmp_path / "multipagina.pdf"
    make_pdf(
        source,
        [
            "FACTURA PAGINA UNO CON TEXTO DIGITAL SUFICIENTE PARA EXTRAER",
            "PAGINA DOS CON PARTIDAS Y TOTAL DEL MISMO DOCUMENTO FISCAL",
        ],
    )
    calls = []

    def forbidden_ocr():
        calls.append(True)
        raise AssertionError("OCR should not be initialized for a digital PDF")

    result = HybridTextEngine(ocr_factory=forbidden_ocr).read(str(source))

    assert result.provider == "pdf-text-native"
    assert len(result.raw["pages"]) == 2
    assert "PÁGINA 1" in result.text
    assert "PÁGINA 2" in result.text
    assert not calls


def test_pdf_without_enough_native_text_uses_ocr(tmp_path):
    source = tmp_path / "escaneado.pdf"
    make_pdf(source, ["corto"])

    result = HybridTextEngine(ocr_factory=FakeOcrEngine).read(str(source))

    assert result.provider == "fake-ocr"


def test_paddle_loader_accepts_multipage_pdf(tmp_path):
    source = tmp_path / "dos-paginas.pdf"
    make_pdf(source, ["uno", "dos"])

    images = PaddleOcrEngine._load_inputs(str(source))

    assert len(images) == 2
    assert all(image.ndim == 3 for image in images)


def test_cfdi_xml_is_read_structurally_without_ocr(tmp_path):
    source = tmp_path / "factura.xml"
    source.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
          xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" Version="4.0"
          Serie="A" Folio="1088" Fecha="2026-08-11T12:00:00"
          SubTotal="1000.00" Descuento="0" Total="1160.00">
          <cfdi:Emisor Rfc="PDC010101CC3" Nombre="PROVEEDOR FICTICIO GAMMA" />
          <cfdi:Receptor Rfc="DEM010101AA1" Nombre="RESTAURANTE DEMO UNO" />
          <cfdi:Conceptos><cfdi:Concepto Cantidad="2" Descripcion="QUESO MANCHEGO" Importe="1000.00" /></cfdi:Conceptos>
          <cfdi:Impuestos TotalImpuestosTrasladados="160.00"><cfdi:Traslados>
            <cfdi:Traslado Impuesto="002" Importe="160.00" />
          </cfdi:Traslados></cfdi:Impuestos>
          <cfdi:Complemento><tfd:TimbreFiscalDigital UUID="123e4567-e89b-42d3-a456-426614174000" /></cfdi:Complemento>
        </cfdi:Comprobante>""",
        encoding="utf-8",
    )

    result = HybridTextEngine(ocr_factory=lambda: (_ for _ in ()).throw(AssertionError())).read(str(source))
    fields = extract_invoice_fields(result.text)

    assert result.provider == "cfdi-xml"
    assert fields["proveedor_propuesto"] == "PROVEEDOR FICTICIO GAMMA"
    assert fields["rfc_emisor"] == "PDC010101CC3"
    assert fields["folio"] == "A1088"
    assert fields["subtotal"] == 1000
    assert fields["iva"] == 160
    assert fields["total"] == 1160
    assert "QUESO MANCHEGO" in result.text


def test_cfdi_xml_rejects_external_entities(tmp_path):
    source = tmp_path / "unsafe.xml"
    source.write_text('<!DOCTYPE x [<!ENTITY file SYSTEM "file:///etc/passwd">]><Comprobante/>')

    try:
        HybridTextEngine().read(str(source))
    except ValueError as exc:
        assert "externa" in str(exc)
    else:
        raise AssertionError("Unsafe XML should have been rejected")
