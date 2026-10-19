from pathlib import Path

import fitz
import numpy as np
import pytest

from app import qr_sat
from app.ocr.base import OcrDocument
from app.text_processing import HybridTextEngine

SAT_URL = (
    "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
    "?id=123e4567-e89b-42d3-a456-426614174000&re=AAA010101AAA&rr=BBB010101BBB&tt=0000004640.000000&fe=abcd1234"
)


def test_parse_sat_url_extracts_uuid_rfcs_and_total():
    parsed = qr_sat.parse_sat_url(SAT_URL)

    assert parsed == {
        "uuid": "123e4567-e89b-42d3-a456-426614174000",
        "emisor_rfc": "AAA010101AAA",
        "receptor_rfc": "BBB010101BBB",
        "total": "4640.00",
    }


def test_non_sat_qr_is_ignored():
    assert qr_sat.parse_sat_url("https://example.com/?id=1") is None
    assert qr_sat.parse_sat_url("") is None


@pytest.mark.skipif(not qr_sat.available(), reason="zxing-cpp no instalado")
def test_qr_is_read_from_a_pdf_page(tmp_path):
    import zxingcpp

    bitmap = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, SAT_URL, 300, 300)
    image = np.array(bitmap, dtype=np.uint8)
    rgb = np.stack([image] * 3, axis=-1) if image.ndim == 2 else image
    pixmap = fitz.Pixmap(fitz.csRGB, rgb.shape[1], rgb.shape[0], rgb.tobytes(), False)
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pixmap)
    source = tmp_path / "con-qr.pdf"
    document.save(source)
    document.close()

    found = qr_sat.read_file(source)

    assert len(found) == 1 and found[0]["total"] == "4640.00" and found[0]["page"] == 1


class FakeOcr:
    def read(self, path: str) -> OcrDocument:
        return OcrDocument(text="texto de imagen", lines=[], confidence=0.9, raw={}, provider="fake-ocr", model="t", duration_ms=1)


def test_scanned_pdf_with_text_layer_is_read_by_image_ocr(tmp_path):
    source = tmp_path / "escaneo.pdf"
    document = fitz.open()
    page = document.new_page()
    photo = fitz.Pixmap(fitz.csRGB, 100, 140, bytes([230]) * (100 * 140 * 3), False)
    page.insert_image(page.rect, pixmap=photo)  # foto a toda la hoja
    page.insert_text((72, 72), "capa de texto escaneada con suficientes caracteres para parecer buena")
    document.save(source)
    document.close()

    result = HybridTextEngine(ocr_factory=FakeOcr).read(str(source))

    assert result.provider == "fake-ocr"


def test_digital_pdf_with_a_small_logo_keeps_native_text(tmp_path):
    source = tmp_path / "digital.pdf"
    document = fitz.open()
    page = document.new_page()
    logo = fitz.Pixmap(fitz.csRGB, 20, 20, bytes([10]) * (20 * 20 * 3), False)
    page.insert_image(fitz.Rect(50, 50, 90, 90), pixmap=logo)
    page.insert_text((72, 200), "FACTURA DIGITAL CON TEXTO SUFICIENTE PARA EXTRAER LOS CAMPOS")
    document.save(source)
    document.close()

    def forbidden():
        raise AssertionError("no debe usar OCR de imagen")

    assert HybridTextEngine(ocr_factory=forbidden).read(str(source)).provider == "pdf-text-native"
