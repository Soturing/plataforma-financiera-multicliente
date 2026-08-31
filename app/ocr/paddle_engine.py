import os
import re
import threading
import time
import unicodedata
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

from app.ocr.base import OcrDocument, OcrLine


class PaddleOcrEngine:
    provider = "paddleocr-local"
    model = "PP-OCRv6-tiny-es"

    def __init__(self):
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        self._engine = PaddleOCR(
            lang="es",
            text_detection_model_name="PP-OCRv6_tiny_det",
            text_recognition_model_name="PP-OCRv6_tiny_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
        self._lock = threading.Lock()

    @staticmethod
    def _load_inputs(path: str) -> list[np.ndarray]:
        source = Path(path)
        if source.suffix.lower() == ".pdf":
            with fitz.open(source) as document:
                if not len(document):
                    raise ValueError("El PDF no contiene páginas")
                images = []
                for page in document:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                    images.append(
                        np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                            pixmap.height, pixmap.width, pixmap.n
                        )
                    )
                return images
        with Image.open(source) as image:
            return [np.asarray(image.convert("RGB"))]

    @staticmethod
    def _text_quality(lines: list[OcrLine]) -> float:
        """Combina confianza OCR y señales de una página orientada correctamente."""
        if not lines:
            return 0.0
        confidence = sum(line.confidence for line in lines) / len(lines)
        text = " ".join(line.text for line in lines).upper()
        decomposed = unicodedata.normalize("NFKD", text)
        plain = "".join(char for char in decomposed if not unicodedata.combining(char))
        words = re.findall(r"[A-Z]{3,}", plain)
        signals = sum(
            token in plain
            for token in (
                "TOTAL", "FECHA", "NOTA", "VENTA", "RFC", "CANTIDAD",
                "DESCRIPCION", "TICKET", "REMISION", "RECIBO", "IMPORTE",
            )
        )
        return confidence + min(0.20, len(words) / 100) + min(0.30, signals * 0.04)

    def _predict(self, image: np.ndarray) -> list[OcrLine]:
        with self._lock:
            results = list(self._engine.predict(image))
        if not results:
            return []
        payload = results[0].json.get("res", {})
        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        polygons = payload.get("rec_polys", [])
        return [
            OcrLine(
                text=str(text).strip(),
                confidence=float(scores[index]) if index < len(scores) else 0.0,
                polygon=(
                    polygons[index].tolist()
                    if index < len(polygons) and hasattr(polygons[index], "tolist")
                    else polygons[index] if index < len(polygons) else []
                ),
            )
            for index, text in enumerate(texts)
            if str(text).strip()
        ]

    def _best_orientation(self, image: np.ndarray) -> tuple[list[OcrLine], int, float]:
        base_lines = self._predict(image)
        best = (base_lines, 0, self._text_quality(base_lines))
        average = (
            sum(line.confidence for line in base_lines) / len(base_lines)
            if base_lines else 0.0
        )
        # Las páginas claras no pagan el costo de tres lecturas adicionales.
        if average >= 0.72 and best[2] >= 0.87:
            return best
        for turns, degrees in ((1, 90), (2, 180), (3, 270)):
            candidate_lines = self._predict(np.ascontiguousarray(np.rot90(image, turns)))
            candidate = (candidate_lines, degrees, self._text_quality(candidate_lines))
            if candidate[2] > best[2]:
                best = candidate
        return best

    def read(self, path: str) -> OcrDocument:
        started = time.perf_counter()
        images = self._load_inputs(path)
        lines: list[OcrLine] = []
        page_payloads = []
        page_texts = []
        for page_number, image in enumerate(images, start=1):
            page_lines, rotation_degrees, quality = self._best_orientation(image)
            if not page_lines:
                page_payloads.append({"page": page_number, "rotation_degrees": 0, "lines": []})
                continue
            lines.extend(page_lines)
            page_text = "\n".join(line.text for line in page_lines)
            page_texts.append(f"--- PÁGINA {page_number} ---\n{page_text}")
            page_payloads.append(
                {
                    "page": page_number,
                    "rotation_degrees": rotation_degrees,
                    "orientation_quality": round(quality, 4),
                    "lines": [
                        {
                            "text": line.text,
                            "confidence": line.confidence,
                            "polygon": line.polygon,
                        }
                        for line in page_lines
                    ],
                }
            )
        if not lines:
            raise ValueError("PaddleOCR no devolvió texto")
        confidence = sum(line.confidence for line in lines) / len(lines) if lines else None
        duration_ms = round((time.perf_counter() - started) * 1000)
        return OcrDocument(
            text="\n".join(page_texts),
            lines=lines,
            confidence=confidence,
            raw={"source": "ocr", "pages": page_payloads},
            provider=self.provider,
            model=self.model,
            duration_ms=duration_ms,
        )


_engine: PaddleOcrEngine | None = None
_engine_lock = threading.Lock()


def get_ocr_engine() -> PaddleOcrEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PaddleOcrEngine()
    return _engine
