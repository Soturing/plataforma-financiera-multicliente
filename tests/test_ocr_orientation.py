from app.ocr.base import OcrLine
from app.ocr.paddle_engine import PaddleOcrEngine


def line(text: str, confidence: float) -> OcrLine:
    return OcrLine(text=text, confidence=confidence, polygon=[])


def test_text_quality_prefers_readable_accounting_document():
    sideways = [line("llI 0O xz", 0.52), line("rrnvv", 0.48)]
    upright = [
        line("NOTA DE VENTA", 0.88),
        line("FECHA 10/08/26", 0.91),
        line("TOTAL 384.00", 0.95),
    ]

    assert PaddleOcrEngine._text_quality(upright) > PaddleOcrEngine._text_quality(sideways)
