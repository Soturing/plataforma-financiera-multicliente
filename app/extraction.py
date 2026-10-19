import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.amount_words import amounts_in_words
from app.rfc import GENERIC_RFCS as _GENERIC, PAC_RFCS, find_rfcs, similar


RFC_RE = re.compile(r"\b([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)
GENERIC_RFCS = frozenset({"XAXX010101000", "XEXX010101000"})
UUID_RE = re.compile(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\b", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2})[\-/](\d{1,2})[\-/](\d{1,2})(?!\d)")
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[\-/.](\d{1,2})[\-/.](20\d{2})(?!\d)")
SHORT_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})[\-/](\d{1,2})[\-/](\d{2})(?!\d)")
SPANISH_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[\s\-/]+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
    r"|january|february|march|april|june|july|august|september|october|november|december)[.\s\-/]+(20\d{2}|\d{2})\b",
    re.IGNORECASE,
)
ABBREVIATED_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})[\s\-/]+(ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic|jan|apr|aug|dec)[.\s\-/]+(20\d{2}|\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
ABBREVIATED_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
    "jan": 1, "apr": 4, "aug": 8, "dec": 12,
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
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d{2}", compact):
        # "1.520.10" / "1,520.10": el último separador es el decimal.
        compact = re.sub(r"[.,](?=\d{3}(?:[.,]|$))", "", compact[:-3]) + "." + compact[-2:]
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
            candidate_line = re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", lines[candidate_index])  # tasas: "IVA 16%"
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


DATE_LABEL_GROUPS = (
    ("FECHA DE EMISION", "FECHA EMISION", "FECHA FACTURA", "FECHA DE FACTURA", "FECHA Y HORA DE EMISION"),
    ("FECHA DE EXPEDICION", "FECHA EXPEDICION"),
    ("FECHA Y HORA DE CERTIFICACION", "FECHA DE CERTIFICACION", "FECHA TIMBRADO", "FECHA Y HORA DE TIMBRADO"),
    ("FECHA",),
)
NOT_ISSUE_DATE = re.compile(r"VENCIMIENTO|ADUANA|LIMITE|ENTREGA|PAGO|VIGENCIA")
ISO_DATETIME_RE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})[T ]\d{1,2}:\d{2}")


def _iso_datetime(lines: list[str]) -> date | None:
    """Primera fecha-hora ISO del documento (los CFDI traen la de emisión en este formato)."""
    for line in lines:
        if match := ISO_DATETIME_RE.search(line):
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def _labeled_date(lines: list[str], label_groups: tuple[tuple[str, ...], ...] = DATE_LABEL_GROUPS) -> date | None:
    for labels in label_groups:
        for index, line in enumerate(lines):
            plain = _plain(line)
            if not any(label in plain for label in labels):
                continue
            if NOT_ISSUE_DATE.search(plain):
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


NAME_STOP_WORDS = re.compile(
    r"\b(?:FACTURA|CLIENTE|FECHA|FOLIO|REGIMEN|R\.?F\.?C|TEL|TELEFONO|USO\s+CFDI|METODO|FORMA\s+DE\s+PAGO|CONDICION|"
    r"CONDICIONES|VENCIMIENTO|ENTREGA|DOMICILIO|DIRECCION|LUGAR|MONEDA|SUBTOTAL|TOTAL|IVA|CANT|CANTIDAD|DESCRIPCION|"
    r"UNIDAD|CLAVE|CODIGO|PRECIO|IMPORTE|SELLO|CADENA|CERTIFICADO|COPIA|ORIGINAL|PAGINA|REMISION|NOTA|TICKET|"
    r"RECIBO|SUCURSAL|VENDEDOR|ELABORO|CAPTURA|FIRMA|DATOS|EMISOR|RECEPTOR|COMPROBANTE|EXPORTACION|NOMBRE|"
    r"PEDIDO|ORDEN|RUTA|OBSERVACIONES|LETRA|PESOS|MXN|CFDI|SAT|UUID|FISCAL|PAGO|CREDITO|CONTADO|"
    r"COL|COLONIA|CALLE|AVENIDA|AV|BLVD|CARRETERA|PRIV|C\.?P|ESCANEADO|CAMSCANNER|GENERAL DE LEY|"
    r"PERSONAS MORALES|DEVOLUCIONES|GRACIAS|PREFERENCIA|CONFORMIDAD|PRODUCTOS|ESTIMADO|FAVOR|DOCUMENTO|"
    r"CAJA|SANITAS|CAJERO|TICKET|ATENDIDO|VENDIDO|CANTIDAD|PIEZA|PIEZAS|KILOS?|KG|LUNA\s+SOFT|SOVOS|FINKOK|EDICOM)\b"
)
LEGAL_SUFFIX = re.compile(r"\b(?:S\.?\s?A\.?(?:\s?P\.?\s?I\.?)?\s?(?:DE\s?)?C\.?\s?V\.?|S\.?\s?DE\s?R\.?\s?L\.?(?:\s?DE\s?C\.?\s?V\.?)?|S\.?\s?A\.?|SAPI|SC)\b", re.IGNORECASE)
RECEPTOR_LABELS = ("CLIENTE", "RECEPTOR", "FACTURADO A", "VENDIDO A", "SOLD TO", "DATOS DEL CLIENTE", "ENVIAR A", "ENTREGAR EN", "OBLIGADO")
PAC_CONTEXT = re.compile(r"CADENA ORIGINAL|INFORMACION DE TIMBRE|CERTIFICADO DEL SAT|SELLO DIGITAL|LUNA SOFT|CERTIFICACION", re.IGNORECASE)
CERTIFICATE_NUMBER_RE = re.compile(r"^0{3,}1\d{14,}$")
MONTH_WORDS = {**MONTHS, **ABBREVIATED_MONTHS}


def _own_match(text: str, own_names: tuple[str, ...]) -> bool:
    plain = re.sub(r"[^A-Z0-9 ]+", " ", _plain(text))
    plain = " ".join(plain.split())
    for name in own_names:
        target = " ".join(re.sub(r"[^A-Z0-9 ]+", " ", _plain(name)).split())
        if target and (target in plain or (len(plain) > 6 and plain in target)):
            return True
    return False


def _looks_like_name(line: str, own_names: tuple[str, ...]) -> bool:
    value = line.strip(" -:|_.,;")
    if not 4 <= len(value) <= 80:
        return False
    letters = sum(char.isalpha() for char in value)
    if letters < 4 or letters / max(len(value), 1) < 0.6:
        return False
    if line.strip().endswith(":"):
        return False
    if re.search(r"[+=*<>\[\]{}~^%$/\|]", value) or sum(char.isdigit() for char in value) > 2:
        return False
    if re.search(r"[a-z][A-Z][a-z]", value) and not value.isupper() and not value.istitle():
        return False
    if re.search(r"\d{3,}", value) or "@" in value or "WWW" in value.upper() or "HTTP" in value.upper():
        return False
    if _own_match(value, own_names):
        return False
    plain = _plain(value)
    if re.search(r"LUNA\s+SO[A-Z]{1,2}|SOVOS|FINKOK|EDICOM", plain):
        return False
    if NAME_STOP_WORDS.search(plain) and not LEGAL_SUFFIX.search(value):
        return False
    return True


PLACE_WORDS = re.compile(
    r"\b(?:MONTERREY|NUEVO\s+LEON|NL|SANTA\s+CATARINA|SAN\s+PEDRO|APODACA|ESCOBEDO|GUADALUPE|"
    r"SAN\s+NICOLAS|JERONIMO|DEL\s+VALLE|CENTRO|CIUDAD|CAJEME|SONORA|NAUCALPAN|ZAPOPAN|JALISCO|"
    r"INDUSTRIAL|PARQUE|LECHUGAL|ABASTOS|TUXTLA|ENGRACIA)\b"
)


def _provider_score(index: int, line: str, rfc_lines: list[int], own_names: tuple[str, ...], lines: list[str] | None = None) -> int | None:
    if not _looks_like_name(line, own_names):
        return None
    value = line.strip(" -:|_.,;")
    plain = _plain(value)
    score = 0
    if LEGAL_SUFFIX.search(value):
        score += 5
    if PLACE_WORDS.search(plain):
        score -= 6
    if rfc_lines:
        distance = min(abs(index - rfc) for rfc in rfc_lines)
        score += max(0, 5 - distance)
    if index < 6:
        score += 2
    elif index < 14:
        score += 1
    lines = lines or []
    previous = _plain(lines[index - 1]).strip(" :") if lines and 0 < index <= len(lines) else ""
    if previous in {"NOMBRE", "RAZON SOCIAL", "EMISOR", "NOMBRE DEL EMISOR", "DATOS DEL EMISOR"}:
        score += 3
    words = value.split()
    if len(words) == 1 and len(value) < 8:
        score -= 3
    if len(words) >= 2:
        score += 1
    if value.isupper():
        score += 1
    if len(value) > 60:
        score -= 3
    if re.search(r"(?:DISTRIBUIDORA|COMERCIALIZADORA|COMERCIAL|ALIMENTOS|SERVICIOS|GRUPO|CARNES|PESCADOS|MATERIAS|PRODUCTORA|"
                 r"ABARROTES|IMPRENTA|QUESERIA|CERVEZAS|JUGOS|CONOS|FOODSERVICE|LOGISTICS)", plain):
        score += 2
    return score


def _provider_near_rfc(lines: list[str], rfc_lines: list[int], own_names: tuple[str, ...]) -> str | None:
    """Razón social del emisor: la línea con mejor puntaje (sufijo legal, cercanía al RFC, encabezado)."""
    best: tuple[int, int, str] | None = None
    for index, line in enumerate(lines):
        score = _provider_score(index, line, rfc_lines, own_names, lines)
        if score is None or score < 3:
            continue
        if best is None or (score, -index) > (best[0], -best[1]):
            best = (score, index, line.strip(" -:|_.,;"))
    return best[2] if best else None


def _explicit_provider(lines: list[str]) -> str | None:
    """Valor de una etiqueta explícita "PROVEEDOR:" o "EMISOR:" (no confundir con "Régimen fiscal emisor")."""
    for line in lines:
        match = re.match(r"^\s*(?:PROVEEDOR|EMISOR|NOMBRE\s+DEL\s+EMISOR)\s*[:\-]\s*(.+)$", line, re.IGNORECASE)
        if match and _looks_like_name(match.group(1), ()):
            return match.group(1).strip()
    return None


def _date_is_plausible(value: str) -> bool:
    return bool(_find_date(value))


def _document_number_v2(lines: list[str], rfcs: set[str], uuid_value: str | None) -> tuple[str | None, str | None]:
    """Folio / número del documento. Devuelve (valor, etiqueta). Nunca usa fechas ni números de certificado."""

    def valid(value: str, minimum_digits: int = 3) -> bool:
        compact = value.strip(" .,:;#-")
        if not compact or len(compact) > 26 or not re.search(r"\d", compact):
            return False
        if re.fullmatch(r"[A-Z]{1,3}", compact, re.IGNORECASE):
            return False
        if sum(char.isdigit() for char in compact) < minimum_digits:
            return False
        if re.fullmatch(r"\d{3,4}", compact) and (compact.startswith(("19", "20")) or compact == "601"):
            return False  # año o régimen fiscal, no folio
        if CERTIFICATE_NUMBER_RE.match(compact.replace(" ", "")) or compact.upper().replace(" ", "") in rfcs:
            return False
        if uuid_value and uuid_value.lower() in compact.lower():
            return False
        if _date_is_plausible(compact) and re.search(r"[/\-]", compact):
            return False
        if re.fullmatch(r"\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}", compact):
            return False
        if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", compact):
            return False
        return True

    joined = "\n".join(lines)
    shaped = (
        (r"\b(INV/\d{4}/\d{3,})\b", "factura"),
        (r"\b(F[VC]/[A-Z]{1,4}/\d{3,})\b", "factura"),
        (r"\bCFDI\s+(\d{4,12})\b", "factura"),
        (r"\bFACTURA\s*\(\s*\w{3,10}\s*\)\s*(\d{1,12})\b", "factura"),
        (r"\bCOTIZACI[OÓ0]N\s*[:#-]?\s*(\d{3,12})\b", "cotizacion"),
        (r"\bNV\s*[:#]?\s*(\d{4,10})\b", "nota"),
    )
    for pattern, label in shaped:
        for match in re.finditer(pattern, joined, re.IGNORECASE):
            short_ok = "{3,10}" in pattern  # "FACTURA (Ingreso) 16": folios cortos permitidos
            if valid(match.group(1), 1 if short_ok else 3):
                return match.group(1).strip(), label

    value_head = re.compile(r"^([A-Z]{0,6}[\s-]?\d{3,12})(?![\dA-Za-z.,])", re.IGNORECASE)
    label_patterns = (
        (re.compile(r"SERIE\s*/?\s*FOLIO\s*[:#-]?\s*(.*)$", re.IGNORECASE), "folio"),
        (re.compile(r"(?:^|\b)(?:NO\.?|N[OÚU]M(?:ERO)?\.?|#)\s*(?:DE\s*)?FACTURA\s*[:#-]?\s*(.*)$", re.IGNORECASE), "factura"),
        (re.compile(r"\bFACTURA\s*(?:NO\.?|N[OÚU]M(?:ERO)?\.?|#)\s*[:#-]?\s*(.*)$", re.IGNORECASE), "factura"),
        (re.compile(r"^FACTURA\s*[:#-]\s*(.*)$", re.IGNORECASE), "factura"),
        (re.compile(r"^FACTURA\s*()$", re.IGNORECASE), "factura"),
        (re.compile(r"^FACTURA\s+(?!MTY)([A-Z]?\s?\d{3,12})\s*$", re.IGNORECASE), "factura"),
        (re.compile(r"\bNOTA\s+DE\s+REMISI[OÓ0]N\s*(?:NO\.?|N[Oº°])?\s*[:#-]?\s*(.*)$", re.IGNORECASE), "remision"),
        (re.compile(r"\bREMISI[OÓ0]N\s*(?:NO\.?|N[Oº°?!.]*)?\s*[:#-]?\s*(.*)$", re.IGNORECASE), "remision"),
        (re.compile(r"\bNOTA\s+DE\s+VENTA\s*(?:NO\.?|N[Oº°])?\s*[:#-]?\s*(.*)$", re.IGNORECASE), "nota"),
        (re.compile(r"(?:TICKET|RECIBO)\s*(?:NO\.?|N[OÚU]M(?:ERO)?|#)?\s*[:#-]\s*(.*)$", re.IGNORECASE), "ticket"),
        (re.compile(r"^NV\s*[:#-]?\s*(.*)$", re.IGNORECASE), "nota"),
        (re.compile(r"\bFOLIO(?!\s*FISCAL)(?!\s*INTERNO)(?!\s*SAT)(?!\s*RECIBO)\s*[:#-]?\s*(.*)$", re.IGNORECASE), "folio"),
        (re.compile(r"\bFOLIO\s*INTERNO\s*[:#-]?\s*(.*)$", re.IGNORECASE), "folio_interno"),
        (re.compile(r"^NO\.?\s*[:#-]?\s*(.*)$", re.IGNORECASE), "no"),
    )
    pending: list[tuple[int, str]] = []
    label_rows: list[int] = []
    for index, line in enumerate(lines):
        for pattern, label in label_patterns:
            match = pattern.search(line.strip())
            if not match:
                continue
            label_rows.append(index)
            tail = match.group(1).strip(" .,:;#-")
            token = value_head.match(tail)
            if token and valid(token.group(1)):
                return token.group(1).strip(" .,:;#-"), label
            pending.append((index, label))
            break
    for index, label in pending:
        for follow in lines[index + 1:index + 6]:
            token = value_head.match(follow.strip())
            if token and valid(token.group(1)):
                return token.group(1).strip(" .,:;#-"), label

    # Número suelto cerca de una etiqueta de folio (el OCR separa las cajas del encabezado).
    postal = re.compile(r"^6[4-7]\d{3}$")
    best: tuple[int, str] | None = None
    for index, line in enumerate(lines):
        token = re.fullmatch(r"([A-Z]{0,2}\s?\d{5,12})", line.strip(), re.IGNORECASE)
        if not token or not valid(token.group(1)) or postal.match(token.group(1).replace(" ", "")):
            continue
        distance = min((abs(index - row) for row in label_rows), default=99)
        if distance <= 8 and (best is None or distance < best[0]):
            best = (distance, token.group(1).strip())
    if best:
        return best[1], "numero_cercano"
    return None, None


def _find_dmy_words(lines: list[str]) -> date | None:
    """Fecha partida en tres líneas: día / mes (Sep, Septiembre) / año."""
    for index in range(len(lines) - 2):
        day, month, year = lines[index].strip(), lines[index + 1].strip().rstrip("."), lines[index + 2].strip()
        if re.fullmatch(r"\d{1,2}", day) and month.lower() in MONTH_WORDS and re.fullmatch(r"20\d{2}", year):
            try:
                return date(int(year), MONTH_WORDS[month.lower()], int(day))
            except ValueError:
                continue
    return None


def _amount_pool(lines: list[str]) -> list[Decimal]:
    pool: list[Decimal] = []
    for line in lines:
        repaired = re.sub(
            r"(?<![A-Za-z])([\dOolIC][\dOolIC.,]*[.,][\dOolIC]{2})(?![\dA-Za-z])",
            lambda m: m.group(1).translate(str.maketrans("OolIC", "00110")),
            line,
        )
        for token in re.findall(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})(?![\d])", repaired):
            value = _amount(token)
            if value is not None:
                pool.append(value)
    return pool


def _near(a: Decimal | None, b: Decimal | None, tolerance: str = "0.02") -> bool:
    return a is not None and b is not None and abs(a - b) <= Decimal(tolerance)


def _reconcile(
    total: Decimal, subtotal: Decimal | None, iva: Decimal | None, discount: Decimal | None,
    other: Decimal | None, pool: set[Decimal],
) -> tuple[Decimal | None, Decimal | None]:
    """Ajusta subtotal e IVA para que cuadren con el total: subtotal - descuento + IVA (+ otros) = total."""
    zero, tolerance = Decimal("0"), Decimal("0.02")
    discount, other = discount or zero, other or zero

    def consistent(s: Decimal | None, i: Decimal | None) -> bool:
        return s is not None and abs(s - discount + (i or zero) + other - total) <= tolerance

    if consistent(subtotal, iva) and iva is not None:
        return subtotal, iva
    if subtotal is not None and subtotal - discount <= total + tolerance:
        implied = total - subtotal + discount - other
        if implied <= tolerance or (implied <= subtotal * Decimal("0.17") + tolerance):
            if iva is None or abs(iva - implied) > tolerance:
                return subtotal, max(implied, zero).quantize(Decimal("0.01"))
            return subtotal, iva
    # El subtotal leído no sirve: se busca entre los importes del documento el par (subtotal, IVA) que cuadre.
    best: tuple[Decimal, Decimal] | None = None
    for candidate in sorted(pool, reverse=True):
        if candidate > total + tolerance or candidate < total * Decimal("0.5"):
            continue
        implied = total - candidate + discount - other
        if abs(implied) <= tolerance or (implied in pool and zero < implied <= candidate * Decimal("0.17") + tolerance):
            best = (candidate, max(implied, zero).quantize(Decimal("0.01")))
            break
    if best:
        return best
    if iva is None:
        return total, Decimal("0.00")
    return subtotal, iva


def _select_amounts(lines: list[str], text: str) -> dict[str, Any]:
    """Subtotal, IVA y total con verificación cruzada (importe con letra y aritmética)."""
    zero = Decimal("0")
    pool = _amount_pool(lines)
    pool_set = set(pool)
    subtotal = _labeled_amount(lines, ("SUBTOTAL", "SUB TOTAL", "IMPORTE BRUTO"))
    discount = _labeled_amount(lines, ("DESCUENTO", "BONIFICACION"))
    iva = _labeled_amount(lines, ("IVA", "I.V.A"))
    other_taxes = _labeled_amount(lines, ("IEPS", "RETENCION", "IMPUESTOS"))
    labeled_total = _labeled_amount(lines, ("TOTAL", "IMPORTE TOTAL", "BUENO POR", "TOTAL A PAGAR", "IMPORTE NETO"))
    words = amounts_in_words(text)

    def words_support(value: Decimal) -> int:
        if any(_near(value, w, "0.005") for w in words):
            return 6
        if any(abs(value - w) < 1 and value >= w for w in words):
            return 3
        return 0

    if iva is not None and subtotal is not None and iva > subtotal * Decimal("0.17") + Decimal("0.02"):
        iva = None  # el "IVA" leído es una columna del renglón, no el impuesto de la factura
    if labeled_total is not None and 0 < labeled_total < Decimal("1"):
        labeled_total = None  # tasas como "0.16" no son importes
    derived = None
    if subtotal is not None:
        derived = subtotal - (discount or zero) + (iva or zero) + (other_taxes or zero)

    def has_sum(value: Decimal) -> bool:
        return any(a >= b > 0 and (value - a) in pool_set for a in pool_set for b in [value - a] if a < value)

    candidates: dict[Decimal, int] = {}
    for value in (labeled_total, derived, *[w for w in words if w in pool_set]):
        if value is not None and value > 0:
            candidates.setdefault(value, 0)
    for value in pool_set:  # cualquier importe del documento que coincida con el importe con letra
        if words_support(value) >= 3:
            candidates.setdefault(value, 0)
    for value in list(candidates):
        score = words_support(value)
        score += 1 if value in pool_set else 0
        score += 2 if _near(value, labeled_total) else 0
        score += 2 if _near(value, derived) else 0
        score += 1 if has_sum(value) else 0
        candidates[value] = score
    total = None
    if candidates:
        total = max(candidates, key=lambda value: (candidates[value], _near(value, labeled_total), value))
        if words and words_support(total) < 3:
            largest = max(words)
            # Un importe con letra mayor que todo lo leído en números suele ser el completo
            # (el OCR perdió el total numérico); uno menor suele estar truncado.
            if largest > total + Decimal("0.01") and largest >= max(labeled_total or zero, subtotal or zero):
                total = largest
    elif words:
        total = max(words)
    if labeled_total == 0 and (total is None or words_support(total) < 3):
        total = None  # el documento dice "TOTAL: 0.00": se deja vacío para revisión humana
    verified = bool(total is not None and (words_support(total) >= 3 or _near(total, derived)))

    if total is not None:
        subtotal, iva = _reconcile(total, subtotal, iva, discount, other_taxes, pool_set)
    return {
        "subtotal": subtotal, "descuento": discount, "iva": iva, "otros_impuestos": other_taxes,
        "total": total, "total_verificado": verified,
    }


def _classify_rfcs(
    text: str, own_rfcs: tuple[str, ...], known_rfcs: tuple[str, ...], lines: list[str]
) -> tuple[list[dict], list[dict]]:
    """Separa RFC del emisor (candidatos) y del receptor (propios del grupo)."""
    known = tuple(own_rfcs) + tuple(known_rfcs)
    receptor, emisor = [], []
    for entry in find_rfcs(text, known):
        rfc = entry["rfc"]
        if rfc in PAC_RFCS or rfc in _GENERIC or entry["entre_barras"]:
            continue
        if all(
            any(PAC_CONTEXT.search(_plain(lines[j])) for j in range(max(0, line - 3), line + 1))
            for line in entry["lineas"]
        ):
            continue
        (receptor if any(similar(rfc, own, 2) for own in own_rfcs) else emisor).append(entry)
    emisor.sort(key=lambda e: (not e["valido"], -e["veces"], e["primera_linea"]))
    return emisor, receptor


def _level(level: str, reason: str) -> dict[str, str]:
    return {"nivel": level, "motivo": reason}


def _field_confidence(
    *, qr: dict[str, Any] | None, rfc_emisor: str | None, emisor_entries: list[dict], provider: str | None,
    provider_source: str | None, folio: str | None, folio_label: str | None, issue_date: date | None,
    date_source: str, amounts: dict[str, Any], total: Decimal | None,
) -> dict[str, dict[str, str]]:
    """Qué tan confiable es cada campo y por qué: la revisión humana empieza por los dudosos."""
    result: dict[str, dict[str, str]] = {}

    if rfc_emisor is None:
        result["rfc_emisor"] = _level("baja", "No se encontró el RFC del emisor")
    elif qr and qr.get("emisor_rfc"):
        result["rfc_emisor"] = _level("alta", "Coincide con el QR del SAT")
    else:
        entry = next((item for item in emisor_entries if item["rfc"] == rfc_emisor), None)
        if entry and entry["valido"] and entry["veces"] >= 2:
            result["rfc_emisor"] = _level("alta", "RFC válido y repetido en el documento")
        elif entry and entry["valido"]:
            result["rfc_emisor"] = _level("media", "RFC válido, visto una sola vez")
        else:
            result["rfc_emisor"] = _level("baja", "El dígito verificador no valida: puede haber un error de lectura")

    if not provider:
        result["proveedor_propuesto"] = _level("baja", "No se identificó el proveedor")
    elif provider_source == "etiqueta":
        result["proveedor_propuesto"] = _level("alta", "Indicado con la etiqueta Proveedor/Emisor")
    elif provider_source == "puntaje" and LEGAL_SUFFIX.search(provider):
        result["proveedor_propuesto"] = _level("alta", "Razón social con sufijo legal junto al RFC del emisor")
    elif provider_source == "puntaje":
        result["proveedor_propuesto"] = _level("media", "Nombre cercano al RFC del emisor")
    else:
        result["proveedor_propuesto"] = _level("baja", "Tomado del encabezado; confirme que es el emisor")

    if folio is None:
        result["folio"] = _level("baja", "No se encontró folio; se usó la fecha como referencia")
    elif folio_label == "numero_cercano":
        result["folio"] = _level("baja", "Número suelto cerca de la etiqueta de folio")
    elif folio_label in {"factura", "cotizacion"}:
        result["folio"] = _level("alta", "Leído junto a su etiqueta")
    else:
        result["folio"] = _level("media", "Leído junto a su etiqueta")

    if issue_date is None:
        result["fecha_emision"] = _level("baja", "No se encontró la fecha")
    elif date_source in {"etiqueta", "iso"}:
        result["fecha_emision"] = _level("alta", "Fecha de emisión con su etiqueta")
    elif date_source == "certificacion":
        result["fecha_emision"] = _level("media", "Fecha de certificación o tomada de la cuadrícula del encabezado")
    else:
        result["fecha_emision"] = _level("baja", "Primera fecha suelta del documento; puede no ser la de emisión")

    if total is None:
        result["total"] = _level("baja", "No se encontró el total")
    elif amounts.get("total_verificado"):
        result["total"] = _level("alta", "Coincide con el importe con letra, el QR o la suma de subtotal e IVA")
    else:
        result["total"] = _level("media", "Leído junto a la etiqueta Total; sin segunda fuente que lo confirme")

    subtotal, iva = amounts.get("subtotal"), amounts.get("iva")
    if subtotal is not None and total is not None:
        cuadra = abs(
            subtotal - (amounts.get("descuento") or Decimal("0")) + (iva or Decimal("0"))
            + (amounts.get("otros_impuestos") or Decimal("0")) - total
        ) <= Decimal("0.02")
        level = "alta" if cuadra and amounts.get("total_verificado") else "media" if cuadra else "baja"
        reason = "Cuadra con el total" if cuadra else "No cuadra con el total: revise subtotal, descuento e IVA"
        result["subtotal"] = _level(level, reason)
        if iva is not None:
            result["iva"] = _level(level, reason)
    return result


def extract_invoice_fields(
    text: str,
    *,
    own_rfcs: tuple[str, ...] = (),
    own_names: tuple[str, ...] = (),
    known_rfcs: tuple[str, ...] = (),
    qr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lee los campos de una factura, remisión o ticket a partir del texto leído.

    `own_rfcs`/`own_names`: RFC y razones sociales del propio grupo (receptores); nunca son el proveedor.
    `known_rfcs`: RFC de proveedores ya catalogados, para corregir errores de OCR.
    `qr`: datos del QR del SAT (`uuid`, `emisor_rfc`, `receptor_rfc`, `total`), fuente prioritaria.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    own_rfcs = tuple(rfc.upper() for rfc in own_rfcs)

    emisor_entries, receptor_entries = _classify_rfcs(joined, own_rfcs, tuple(known_rfcs), lines)
    rfc_emisor = emisor_entries[0]["rfc"] if emisor_entries else None
    rfc_receptor = receptor_entries[0]["rfc"] if receptor_entries else None
    rfc_lines = emisor_entries[0]["lineas"] if emisor_entries else []
    uuid_match = UUID_RE.search(joined)
    uuid_value = uuid_match.group(1).lower() if uuid_match else None
    if qr:
        rfc_emisor = (qr.get("emisor_rfc") or rfc_emisor or None)
        rfc_receptor = qr.get("receptor_rfc") or rfc_receptor
        uuid_value = (qr.get("uuid") or uuid_value or None)
        uuid_value = uuid_value.lower() if uuid_value else None
        if qr.get("emisor_rfc"):
            for entry in find_rfcs(joined, (qr["emisor_rfc"],)):
                if entry["rfc"] == qr["emisor_rfc"].upper():
                    rfc_lines = entry["lineas"]

    all_rfcs = {entry["rfc"] for entry in emisor_entries + receptor_entries} | {rfc for rfc in (rfc_emisor, rfc_receptor) if rfc}
    provider_source = None
    provider = _explicit_provider(lines)
    if provider:
        provider_source = "etiqueta"
    if not provider:
        provider = _provider_near_rfc(lines, rfc_lines, tuple(own_names))
        provider_source = "puntaje" if provider else None
    if not provider:
        header = _header_provider([line for line in lines if not _own_match(line, tuple(own_names))])
        provider = header if header and _looks_like_name(header, tuple(own_names)) and (len(header.split()) >= 2 or len(header) >= 8) else None
        provider_source = "encabezado" if provider else None

    date_source = "etiqueta"
    parsed_date = _labeled_date(lines, DATE_LABEL_GROUPS[:2])
    if parsed_date is None:
        date_source = "iso"
        parsed_date = _iso_datetime(lines)
    if parsed_date is None:
        date_source = "certificacion"
        parsed_date = _labeled_date(lines, DATE_LABEL_GROUPS[2:]) or _find_dmy_words(lines)
    if parsed_date is None:
        date_source = "suelta"
        parsed_date = _find_date(joined)
    detected_folio, folio_label = _document_number_v2(lines, all_rfcs, uuid_value)
    if detected_folio is None:
        legacy = _document_number(lines)
        if (
            legacy
            and sum(char.isdigit() for char in legacy) >= 3
            and len(legacy) <= 20
            and not CERTIFICATE_NUMBER_RE.match(legacy.replace(" ", ""))
            and not re.fullmatch(r"[A-Z]{1,5}\d?|(?:19|20)\d{2}", legacy, re.IGNORECASE)
        ):
            detected_folio = legacy

    amounts = _select_amounts(lines, joined)
    if qr and qr.get("total"):
        qr_total = _amount(str(qr["total"]))
        if qr_total is not None and qr_total > 0:
            if amounts["total"] is None or not _near(amounts["total"], qr_total):
                refreshed = _select_amounts(lines, joined)
                amounts.update(total=qr_total, descuento=refreshed["descuento"], otros_impuestos=refreshed["otros_impuestos"])
                amounts["subtotal"], amounts["iva"] = _reconcile(
                    qr_total, refreshed["subtotal"], refreshed["iva"], refreshed["descuento"],
                    refreshed["otros_impuestos"], set(_amount_pool(lines)),
                )
            amounts["total_verificado"] = True
    total = amounts["total"]
    # La base exige totales positivos. Un cero leído por OCR significa que el dato no fue
    # identificado y debe llegar vacío a revisión humana, no hacer fallar todo el documento.
    if total is not None and total <= 0:
        total = None

    confidence = _field_confidence(
        qr=qr, rfc_emisor=rfc_emisor, emisor_entries=emisor_entries, provider=provider,
        provider_source=provider_source, folio=detected_folio, folio_label=folio_label,
        issue_date=parsed_date, date_source=date_source, amounts=amounts, total=total,
    )
    return {
        "proveedor_propuesto": provider,
        "rfc_emisor": rfc_emisor,
        "rfc_receptor": rfc_receptor,
        "rfc_candidates": [entry["rfc"] for entry in emisor_entries],
        "uuid_fiscal": uuid_value,
        "folio": detected_folio or (parsed_date.strftime("%d%m%Y") if parsed_date else None),
        "folio_origen": "detectado" if detected_folio else ("fecha" if parsed_date else None),
        "fecha_emision": parsed_date,
        "subtotal": amounts["subtotal"],
        "descuento": amounts["descuento"],
        "iva": amounts["iva"],
        "otros_impuestos": amounts["otros_impuestos"],
        "total": total,
        "total_verificado": amounts["total_verificado"],
        "fuente_qr": bool(qr),
        "confianza_campos": confidence,
    }
