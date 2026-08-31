import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


RFC_RE = re.compile(r"\b([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)
GENERIC_RFCS = frozenset({"XAXX010101000", "XEXX010101000"})
UUID_RE = re.compile(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2})[\-/](\d{1,2})[\-/](\d{1,2})(?!\d)")
DATE_RE = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](20\d{2})(?!\d)")
SHORT_DATE_RE = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{2})(?!\d)")
SPANISH_DATE_RE = re.compile(
    r"\b(\d{1,2})[\s\-/]+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)[.\s\-/]+(20\d{2}|\d{2})\b",
    re.IGNORECASE,
)
ABBREVIATED_DATE_RE = re.compile(
    r"\b(\d{1,2})[\s\-/]+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[.\s\-/]+(20\d{2}|\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
ABBREVIATED_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}
AMOUNT_RE = re.compile(r"(?:\$|MXN)?\s*([0-9][0-9.,\s]*[.,]\d{2})\b", re.IGNORECASE)
INTEGER_AMOUNT_RE = re.compile(r"(?:\$|MXN)?\s*((?:\d{1,3}(?:,\d{3})+)|(?:\d{2,6}))(?!\d)", re.IGNORECASE)
LOOSE_AMOUNT_RE = re.compile(r"(?:\$|MXN)?\s*([0-9][0-9.,]{2,})(?!\d)", re.IGNORECASE)
DOCUMENT_NUMBER_PATTERNS = (
    re.compile(r"(?:N[OÚU]M(?:ERO)?\.?\s*(?:DE\s*)?FACTURA|NO\.?\s*(?:DE\s*)?FACTURA|FACTURA\s*(?:NO\.?|N[OÚU]M(?:ERO)?|#))\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{0,39})", re.IGNORECASE),
    re.compile(r"(?:N[OÚU]M(?:ERO)?\.?\s*(?:DE\s*)?NOTA|NO\.?\s*(?:DE\s*)?NOTA|NOTA\s*(?:NO\.?|N[OÚU]M(?:ERO)?|#))\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{0,39})", re.IGNORECASE),
    re.compile(r"(?:TICKET|RECIBO)\s*(?:NO\.?|N[OÚU]M(?:ERO)?|#)?\s*[:#-]\s*([A-Z0-9][A-Z0-9./_-]{0,39})", re.IGNORECASE),
    re.compile(r"\bTC\s*#\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]{3,39})", re.IGNORECASE),
    re.compile(r"\bFOLIO(?!\s+FISCAL)\s*[:#-]\s*([A-Z0-9][A-Z0-9./_-]{0,39})", re.IGNORECASE),
)
DOCUMENT_NUMBER_LABEL_RE = re.compile(
    r"^(?:#\s*DE\s*TICKET|N[OÚU]M(?:ERO)?\.?\s*(?:DE\s*)?(?:FACTURA|NOTA)|NO\.?\s*(?:DE\s*)?(?:FACTURA|NOTA)|(?:FACTURA|NOTA|TICKET|RECIBO)\s*(?:NO\.?|N[OÚU]M(?:ERO)?|#)?|FOLIO)\s*[:#-]?\s*$",
    re.IGNORECASE,
)
DOCUMENT_NUMBER_VALUE_RE = re.compile(r"^\s*([A-Z0-9][A-Z0-9./_-]{0,39})\s*$", re.IGNORECASE)


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.upper())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _amount(value: str) -> Decimal | None:
    compact = value.replace(" ", "")
    if compact.count(",") and compact.count("."):
        compact = compact.replace(",", "")
    elif compact.count(",") == 1 and len(compact.rsplit(",", 1)[1]) == 2:
        compact = compact.replace(",", ".")
    elif compact.count(".") == 1 and len(compact.rsplit(".", 1)[1]) == 3:
        compact = compact.replace(".", "")
    else:
        compact = compact.replace(",", "")
    try:
        return Decimal(compact).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _labeled_amount(lines: list[str], labels: tuple[str, ...]) -> Decimal | None:
    candidates: list[tuple[int, int, int, int, Decimal, Decimal]] = []
    for index, line in enumerate(lines):
        plain = _plain(line)
        label_text = re.sub(r"[$\d.,]+", " ", plain)
        compact_label = re.sub(r"[^A-Z]", "", label_text)
        if "CONLETRA" in compact_label:
            continue
        matched = [label for label in labels if label.replace(" ", "") in compact_label]
        if not matched:
            continue
        exact_penalty = 0 if compact_label in {label.replace(" ", "") for label in matched} else 1
        context = " ".join(_plain(item) for item in lines[max(0, index - 2):index + 3])
        header_penalty = 1 if sum(token in context for token in ("CANT", "PVENTA", "P UNITARIO", "DESCRIPCION")) >= 2 else 0
        for distance, candidate_index in enumerate(
            (index, index + 1, index + 2, index + 3, index - 1, index - 2, index - 3)
        ):
            if not 0 <= candidate_index < len(lines):
                continue
            candidate_line = lines[candidate_index]
            repaired = re.sub(
                r"(?<![A-Za-z])[\d.,lIoO]+(?![A-Za-z])",
                lambda match: match.group(0).translate(str.maketrans("lIoO", "1100")),
                candidate_line,
            )
            matches = AMOUNT_RE.findall(repaired)
            if not matches:
                matches = LOOSE_AMOUNT_RE.findall(repaired)
            if not matches:
                matches = INTEGER_AMOUNT_RE.findall(repaired)
            if not matches:
                continue
            amount = _amount(matches[-1])
            if amount is not None:
                zero_penalty = 1 if amount == 0 else 0
                candidates.append((exact_penalty, header_penalty, distance, zero_penalty, -amount, amount))
                break
    return min(candidates, default=(0, 0, 0, 0, Decimal("0"), None))[-1]


def _date_from_match(match: re.Match[str], month_map: dict[str, int] | None = None) -> date | None:
    try:
        if match.re is ISO_DATE_RE:
            year, month, day = map(int, match.groups())
        elif month_map is not None:
            day, month_name, year = match.groups()
            month = month_map[month_name.lower()]
            day, year = int(day), int(year)
        else:
            day, month, year = map(int, match.groups())
        if year < 100:
            year += 2000
        return date(year, month, day)
    except (KeyError, ValueError):
        return None


def _find_date(value: str) -> date | None:
    patterns = (
        (ISO_DATE_RE, None),
        (DATE_RE, None),
        (SHORT_DATE_RE, None),
        (SPANISH_DATE_RE, MONTHS),
        (ABBREVIATED_DATE_RE, ABBREVIATED_MONTHS),
    )
    for pattern, month_map in patterns:
        if match := pattern.search(value):
            if parsed := _date_from_match(match, month_map):
                return parsed
    return None


def _labeled_date(lines: list[str]) -> date | None:
    label_groups = (
        ("FECHA DE EMISION", "FECHA EMISION", "FECHA FACTURA", "FECHA DE FACTURA"),
        ("FECHA DE EXPEDICION", "FECHA EXPEDICION"),
        ("FECHA Y HORA DE CERTIFICACION", "FECHA DE CERTIFICACION"),
        ("FECHA",),
    )
    for labels in label_groups:
        for index, line in enumerate(lines):
            plain = _plain(line)
            if not any(label in plain for label in labels):
                continue
            for candidate_index in (index, index + 1, index + 2, index - 1):
                if 0 <= candidate_index < len(lines):
                    if parsed := _find_date(lines[candidate_index]):
                        return parsed
            numeric_parts = []
            for candidate in lines[index + 1:index + 10]:
                repaired = candidate.strip().replace("O", "0").replace("o", "0")
                repaired = repaired.replace("C", "6").replace("c", "6")
                if re.fullmatch(r"\d{1,2}[.]?", repaired):
                    numeric_parts.append(int(repaired.rstrip(".")))
                if len(numeric_parts) == 3:
                    break
            years = [part for part in numeric_parts if 20 <= part <= 99]
            if len(numeric_parts) == 3 and len(years) == 1:
                year = years[0]
                day_month = numeric_parts.copy()
                day_month.remove(year)
                if len(day_month) == 2:
                    try:
                        return date(2000 + year, day_month[1], day_month[0])
                    except ValueError:
                        pass
    return None


def _document_number(lines: list[str]) -> str | None:
    joined = "\n".join(lines)
    structured = re.search(
        r"(?:REMISI[OÓ0]N|NOTA\s+DE\s+VENTA)[\s\S]{0,100}?N[O0º°?!.]*\s*[:#-]?\s*(\d{2,20})",
        joined,
        re.IGNORECASE,
    )
    if structured:
        return structured.group(1)
    for index, line in enumerate(lines):
        for pattern in DOCUMENT_NUMBER_PATTERNS:
            if match := pattern.search(line):
                value = match.group(1).strip(" .,:;#-")
                if value:
                    return value
        if DOCUMENT_NUMBER_LABEL_RE.match(line.strip()) and index + 1 < len(lines):
            if match := DOCUMENT_NUMBER_VALUE_RE.match(lines[index + 1]):
                return match.group(1).strip(" .,:;#-")
        if re.fullmatch(r"TC\s*#\s*[:#-]?", line.strip(), re.IGNORECASE) and index + 1 < len(lines):
            if match := DOCUMENT_NUMBER_VALUE_RE.match(lines[index + 1]):
                return match.group(1).strip(" .,:;#-")
    return None


def _header_provider(lines: list[str]) -> str | None:
    ignored = re.compile(
        r"P[ÁA]GINA|REMISI[OÓ0]N|RECIBO(?:\s+DE\s+DINERO)?|NOTA\s+DE\s+VENTA|"
        r"FACTURA|FECHA|N[ÚU]M\.?|^NO\.?$|TOTAL|BUENO\s+POR|^DE\s+DINERO$|"
        r"LA\s+CANTIDAD|CONCEPTO|PAGO(?:\s+HECHO)?\s+EN|EFECTIVO|FIRMA|RECIB[IÍ]",
        re.IGNORECASE,
    )
    candidates = []
    target_parts = 1
    for line in lines[:14]:
        plain = line.strip(" -:|_")
        if not plain or ignored.search(plain) or not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", plain):
            continue
        # Paddle puede confundir 1/0 con l/I/O en importes manuscritos. Una
        # linea numerica como "1.loo" no es el nombre del proveedor.
        numeric_like = plain.translate(str.maketrans("lIoO", "1100"))
        if re.fullmatch(r"[$\s\d.,/-]+", numeric_like):
            continue
        if re.match(r"^\d", plain) or sum(char.isalpha() for char in plain) < 3:
            continue
        if re.search(
            r"\b(?:RFC|R\.F\.C|CALLE|AV\.|COL\.|DOMICILIO|DIRECCION)\b",
            plain,
            re.IGNORECASE,
        ):
            if candidates:
                break
            continue
        if len(plain) > 80:
            continue
        candidates.append(plain)
        if len(candidates) == 1 and plain.upper().endswith(" DE"):
            target_parts = 3
        if len(candidates) >= target_parts:
            break
    return " ".join(candidates[:3]) or None


def extract_invoice_fields(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    rfc_candidates = list(dict.fromkeys(
        match.upper()
        for match in RFC_RE.findall(joined)
        if match.upper() not in GENERIC_RFCS
    ))
    uuid_match = UUID_RE.search(joined)
    parsed_date = _labeled_date(lines) or _find_date(joined)
    detected_folio = _document_number(lines)

    provider = None
    for line in lines:
        plain = _plain(line)
        if "PROVEEDOR" in plain or "EMISOR" in plain:
            candidate = re.split(r"[:\-]", line, maxsplit=1)
            if len(candidate) == 2 and candidate[1].strip():
                provider = candidate[1].strip()
                break
    provider = provider or _header_provider(lines)
    total = _labeled_amount(lines, ("TOTAL", "IMPORTE TOTAL", "BUENO POR"))
    # La base exige totales positivos. Un cero leído por OCR significa que el
    # dato no fue identificado y debe llegar vacío a revisión humana, no hacer
    # fallar todo el documento.
    if total is not None and total <= 0:
        total = None

    return {
        "proveedor_propuesto": provider,
        "rfc_emisor": rfc_candidates[0] if rfc_candidates else None,
        "rfc_candidates": rfc_candidates,
        "uuid_fiscal": uuid_match.group(1).lower() if uuid_match else None,
        "folio": detected_folio or (parsed_date.strftime("%d%m%Y") if parsed_date else None),
        "folio_origen": "detectado" if detected_folio else ("fecha" if parsed_date else None),
        "fecha_emision": parsed_date,
        "subtotal": _labeled_amount(lines, ("SUBTOTAL",)),
        "descuento": _labeled_amount(lines, ("DESCUENTO",)),
        "iva": _labeled_amount(lines, ("IVA", "I.V.A")),
        "otros_impuestos": _labeled_amount(lines, ("IEPS", "RETENCION", "IMPUESTOS")),
        "total": total,
    }
