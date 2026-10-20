"""Lectura del código QR del SAT de un CFDI.

El QR contiene la liga de verificación del SAT con el UUID (`id`), el RFC del emisor (`re`),
el del receptor (`rr`) y el total (`tt`): datos sin ambigüedad que no dependen del OCR.
Si `zxing-cpp` no está disponible la lectura se omite y el flujo sigue con OCR.
"""

import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import fitz
import numpy as np

log = logging.getLogger("facturas.qr")

try:  # dependencia opcional
    import zxingcpp
except ImportError:  # pragma: no cover
    zxingcpp = None

SAT_HOST = "sat.gob.mx"
ZOOMS = (2.0, 3.0, 4.0)


def available() -> bool:
    return zxingcpp is not None


def parse_sat_url(text: str) -> dict[str, Any] | None:
    """Extrae uuid / RFC / total de la URL del QR del SAT; None si no es un QR del SAT."""
    if SAT_HOST not in (text or "").lower():
        return None
    query = {key.lower(): value[0] for key, value in parse_qs(urlparse(text).query).items()}
    emisor = (query.get("re") or "").upper().strip() or None
    receptor = (query.get("rr") or "").upper().strip() or None
    uuid = (query.get("id") or "").lower().strip() or None
    total = None
    try:
        raw_total = (query.get("tt") or "").replace(",", "")
        total = Decimal(raw_total).quantize(Decimal("0.01")) if raw_total else None
    except InvalidOperation:
        total = None
    if not (uuid or emisor or total):
        return None
    if uuid and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", uuid):
        uuid = None
    return {"uuid": uuid, "emisor_rfc": emisor, "receptor_rfc": receptor, "total": str(total) if total is not None else None}


def _decode(image: np.ndarray) -> dict[str, Any] | None:
    for barcode in zxingcpp.read_barcodes(image):
        if parsed := parse_sat_url(barcode.text):
            return parsed
    return None


def read_pdf_page(document: "fitz.Document", page_index: int) -> dict[str, Any] | None:
    page = document[page_index]
    for zoom in ZOOMS:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
        if parsed := _decode(image):
            return {**parsed, "page": page_index + 1}
    return None


def read_file(path: str | Path) -> list[dict[str, Any]]:
    """QR del SAT de cada página de un PDF o imagen (lista vacía si no hay o no hay lector)."""
    if zxingcpp is None:
        return []
    source = Path(path)
    results: list[dict[str, Any]] = []
    try:
        if source.suffix.lower() == ".pdf":
            with fitz.open(source) as document:
                for index in range(len(document)):
                    if found := read_pdf_page(document, index):
                        results.append(found)
        elif source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            from PIL import Image

            with Image.open(source) as handle:
                base = handle.convert("RGB")
                for scale in (1.0, 1.5, 2.0):
                    resized = base if scale == 1.0 else base.resize((int(base.width * scale), int(base.height * scale)))
                    if found := _decode(np.asarray(resized)):
                        results.append({**found, "page": 1})
                        break
    except Exception:
        log.warning("Falló la decodificación del QR; se devuelven los resultados parciales", exc_info=True)
        return results
    return results
