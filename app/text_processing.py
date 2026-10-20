from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import fitz
from pypdf import PdfReader

from app import qr_sat, xml_seguro
from app.errors import DomainError
from app.ocr.base import OcrDocument, OcrEngine, OcrLine
from app.ocr.paddle_engine import get_ocr_engine

log = logging.getLogger("facturas.texto")


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
            return self._with_qr(self.ocr_factory().read(path), path)

        native = self._read_native_pdf(source)
        pages = native.raw["pages"]
        # Los PDF de apps de escaneo (CamScanner, etc.) traen una capa de texto pobre o girada que
        # parece "suficiente": si la página es una foto, se lee la imagen en lugar de confiar en ella.
        if (
            pages
            and all(page["characters"] >= self.min_characters_per_page for page in pages)
            and not self._looks_scanned(source)
        ):
            return self._with_qr(native, path)
        return self._with_qr(self.ocr_factory().read(path), path)

    @staticmethod
    def _looks_scanned(path: Path, coverage: float = 0.6) -> bool:
        """True si la mayoría de las páginas son una imagen que cubre (casi) toda la hoja."""
        try:
            with fitz.open(path) as document:
                scanned = 0
                for page in document:
                    page_area = max(page.rect.width * page.rect.height, 1.0)
                    largest = max(
                        (abs(fitz.Rect(info["bbox"]).width * fitz.Rect(info["bbox"]).height)
                         for info in page.get_image_info()),
                        default=0.0,
                    )
                    scanned += largest / page_area >= coverage
                return bool(len(document)) and scanned / len(document) >= 0.5
        except Exception:
            log.warning("No se pudo evaluar si el PDF es un escaneo; se trata como digital", exc_info=True)
            return False

    @staticmethod
    def _with_qr(document: OcrDocument, path: str) -> OcrDocument:
        """Adjunta el QR del SAT (si lo hay) a `raw["qr_sat"]`; no depende del OCR."""
        try:
            qr = qr_sat.read_file(path)
        except Exception:
            log.warning("Falló la lectura del QR del SAT; se continúa sin él", exc_info=True)
            qr = []
        if qr:
            document.raw["qr_sat"] = qr
        return document

    @staticmethod
    def _read_cfdi_xml(path: Path) -> OcrDocument:
        started = time.perf_counter()
        payload = path.read_bytes()
        try:
            root = xml_seguro.parsear(payload)
        except DomainError as exc:
            raise ValueError("El XML contiene una declaración externa no permitida") from exc
        except xml_seguro.ParseError as exc:
            raise ValueError("El XML no es válido") from exc

        def local_name(element: xml_seguro.Element) -> str:
            return element.tag.rsplit("}", 1)[-1]

        if local_name(root).lower() != "comprobante":
            raise ValueError("El XML no corresponde a un CFDI")

        def attr(element: xml_seguro.Element | None, name: str) -> str | None:
            if element is None:
                return None
            return next(
                (value for key, value in element.attrib.items() if key.lower() == name.lower()),
                None,
            )

        def first(name: str) -> xml_seguro.Element | None:
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
