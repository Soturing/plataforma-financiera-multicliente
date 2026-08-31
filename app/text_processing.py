from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from app.ocr.base import OcrDocument, OcrEngine, OcrLine
from app.ocr.paddle_engine import get_ocr_engine


class HybridTextEngine:
    """Extract embedded PDF text first and use OCR only when it is insufficient."""

    def __init__(
        self,
        *,
        min_characters_per_page: int = 40,
        ocr_factory: Callable[[], OcrEngine] = get_ocr_engine,
    ) -> None:
        self.min_characters_per_page = min_characters_per_page
        self.ocr_factory = ocr_factory

    def read(self, path: str) -> OcrDocument:
        source = Path(path)
        if source.suffix.lower() == ".xml":
            return self._read_cfdi_xml(source)
        if source.suffix.lower() != ".pdf":
            return self.ocr_factory().read(path)

        native = self._read_native_pdf(source)
        pages = native.raw["pages"]
        if pages and all(
            page["characters"] >= self.min_characters_per_page for page in pages
        ):
            return native
        return self.ocr_factory().read(path)

    @staticmethod
    def _read_cfdi_xml(path: Path) -> OcrDocument:
        started = time.perf_counter()
        payload = path.read_bytes()
        guard = payload[:8192].decode("utf-8", errors="ignore").upper()
        if "<!DOCTYPE" in guard or "<!ENTITY" in guard:
            raise ValueError("El XML contiene una declaración externa no permitida")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError("El XML no es válido") from exc

        def local_name(element: ET.Element) -> str:
            return element.tag.rsplit("}", 1)[-1]

        if local_name(root).lower() != "comprobante":
            raise ValueError("El XML no corresponde a un CFDI")

        def attr(element: ET.Element | None, name: str) -> str | None:
            if element is None:
                return None
            return next(
                (value for key, value in element.attrib.items() if key.lower() == name.lower()),
                None,
            )

        def first(name: str) -> ET.Element | None:
            return next((item for item in root.iter() if local_name(item).lower() == name.lower()), None)

        def money(value: str | None) -> Decimal:
            try:
                return Decimal(value or "0").quantize(Decimal("0.01"))
            except InvalidOperation:
                return Decimal("0.00")

        issuer = first("Emisor")
        receiver = first("Receptor")
        stamp = first("TimbreFiscalDigital")
        concepts = [item for item in root.iter() if local_name(item).lower() == "concepto"]
        direct_taxes = root.find("./{*}Impuestos")
        transfers = [] if direct_taxes is None else list(direct_taxes.findall("./{*}Traslados/{*}Traslado"))
        if not transfers:
            transfers = [item for item in root.iter() if local_name(item).lower() == "traslado"]
        iva = sum(
            (money(attr(item, "Importe")) for item in transfers if attr(item, "Impuesto") == "002"),
            Decimal("0"),
        )
        transferred = money(attr(direct_taxes, "TotalImpuestosTrasladados"))
        if not iva and transferred:
            iva = transferred
        other_taxes = max(Decimal("0"), transferred - iva)
        series = attr(root, "Serie") or ""
        folio = attr(root, "Folio") or ""
        document_number = f"{series}{folio}".strip() or None

        lines = ["FACTURA FISCAL CFDI"]
        if attr(issuer, "Nombre"):
            lines.append(f"EMISOR: {attr(issuer, 'Nombre')}")
        if attr(issuer, "Rfc"):
            lines.append(f"RFC EMISOR: {attr(issuer, 'Rfc')}")
        if attr(receiver, "Nombre"):
            lines.append(f"RECEPTOR: {attr(receiver, 'Nombre')}")
        if attr(receiver, "Rfc"):
            lines.append(f"RFC RECEPTOR: {attr(receiver, 'Rfc')}")
        if document_number:
            lines.append(f"FOLIO: {document_number}")
        if attr(root, "Fecha"):
            lines.append(f"FECHA DE EMISION: {attr(root, 'Fecha')}")
        if attr(stamp, "UUID"):
            lines.append(f"UUID: {attr(stamp, 'UUID')}")
        lines.extend(
            [
                f"SUBTOTAL: {money(attr(root, 'SubTotal')):.2f}",
                f"DESCUENTO: {money(attr(root, 'Descuento')):.2f}",
                f"IVA: {iva:.2f}",
                f"OTROS IMPUESTOS: {other_taxes:.2f}",
                f"TOTAL: {money(attr(root, 'Total')):.2f}",
                "CONCEPTOS:",
            ]
        )
        for concept in concepts:
            description = attr(concept, "Descripcion") or "Concepto sin descripción"
            lines.append(
                f"{description} | CANTIDAD {attr(concept, 'Cantidad') or '1'} | "
                f"IMPORTE {money(attr(concept, 'Importe')):.2f}"
            )
        text = "\n".join(lines)
        return OcrDocument(
            text=text,
            lines=[OcrLine(text=line, confidence=1.0, polygon=[]) for line in lines],
            confidence=1.0,
            raw={
                "source": "cfdi_xml",
                "version": attr(root, "Version"),
                "concept_count": len(concepts),
                "issuer": {"name": attr(issuer, "Nombre"), "rfc": attr(issuer, "Rfc")},
                "receiver": {"name": attr(receiver, "Nombre"), "rfc": attr(receiver, "Rfc")},
                "uuid": attr(stamp, "UUID"),
            },
            provider="cfdi-xml",
            model="structured-v1",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _read_native_pdf(path: Path) -> OcrDocument:
        started = time.perf_counter()
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise ValueError("El PDF está protegido con contraseña")
        if not reader.pages:
            raise ValueError("El PDF no contiene páginas")

        page_payloads: list[dict[str, object]] = []
        lines: list[OcrLine] = []
        document_parts: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\x00", "").strip()
            page_lines = [line.strip() for line in text.splitlines() if line.strip()]
            page_payloads.append(
                {
                    "page": page_number,
                    "characters": len(text),
                    "lines": page_lines,
                }
            )
            if text:
                document_parts.append(f"--- PÁGINA {page_number} ---\n{text}")
                lines.extend(
                    OcrLine(text=line, confidence=1.0, polygon=[])
                    for line in page_lines
                )

        return OcrDocument(
            text="\n".join(document_parts),
            lines=lines,
            confidence=1.0,
            raw={"source": "embedded_pdf_text", "pages": page_payloads},
            provider="pdf-text-native",
            model="pypdf",
            duration_ms=round((time.perf_counter() - started) * 1000),
        )


_engine: HybridTextEngine | None = None


def get_text_engine() -> HybridTextEngine:
    global _engine
    if _engine is None:
        _engine = HybridTextEngine()
    return _engine
