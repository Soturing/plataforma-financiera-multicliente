"""Validación y corrección de RFC mexicanos leídos por OCR.

El último carácter del RFC es un dígito verificador (módulo 11), así que un RFC mal leído
casi nunca valida; con eso se pueden corregir las confusiones típicas del OCR (0/O/D,
1/I/J, 5/S, 8/B/9...) sin depender de un catálogo.
"""

import itertools
import re
from datetime import date

_ALPHABET = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ"
_VALUE = {char: index for index, char in enumerate(_ALPHABET)}

# Caracteres que los motores de OCR suelen confundir entre sí.
_CONFUSION_GROUPS = ("0OQD", "1ILJU", "5S", "8B96", "6G", "2Z")
_CONFUSABLE: dict[str, str] = {}
for _group in _CONFUSION_GROUPS:
    for _char in _group:
        _CONFUSABLE[_char] = _CONFUSABLE.get(_char, "") + "".join(c for c in _group if c != _char)

# RFC de proveedores autorizados de certificación (PAC) y del SAT: nunca son el emisor.
PAC_RFCS = frozenset({
    "LSO1306189R5", "SAT970701NN3", "SFE0807172W7", "DCD090706E42", "FIE0911135Z9",
    "TSP080724QW6", "ASE0209252Q1", "CCO8605231N4", "EME060201KK3", "PFE110512RM5",
    "SPR190613I52", "PCE100202L9A", "NSD130822E65", "PGD1303122A5", "AAA010101AAA",
})
GENERIC_RFCS = frozenset({"XAXX010101000", "XEXX010101000"})

_TOKEN_RE = re.compile(
    r"(?<![A-Z0-9&Ñ])([A-ZÑ&]{3,4})[\s\-]?([0-9OIL SBGDQ]{6})[\s\-]?([A-Z0-9]{3})(?![A-Z0-9&Ñ])",
    re.IGNORECASE,
)


def _check_digit(body: str) -> str:
    padded = body.rjust(12)  # 12 caracteres sin dígito verificador (persona moral lleva un espacio al inicio)
    total = sum(_VALUE.get(char, 0) * (13 - index) for index, char in enumerate(padded))
    digit = 11 - (total % 11)
    return "0" if digit == 11 else "A" if digit == 10 else str(digit)


def _valid_date(text: str) -> bool:
    if not text.isdigit():
        return False
    year, month, day = int(text[:2]), int(text[2:4]), int(text[4:6])
    try:
        date(2000 + year if year < 70 else 1900 + year, month, day)
        return True
    except ValueError:
        return False


def is_valid_rfc(value: str | None) -> bool:
    rfc = (value or "").upper().replace(" ", "")
    if len(rfc) not in (12, 13) or rfc in GENERIC_RFCS:
        return rfc in GENERIC_RFCS
    prefix = rfc[:-9]
    if not re.fullmatch(r"[A-ZÑ&]{3,4}", prefix) or not _valid_date(rfc[-9:-3]):
        return False
    return _check_digit(rfc[:-1]) == rfc[-1]


def correct_rfc(token: str, known: tuple[str, ...] = (), max_edits: int = 2) -> tuple[str, bool, int]:
    """Devuelve (rfc, valido, ediciones). Corrige confusiones típicas de OCR.

    1. Si el RFC leído se parece (hasta `max_edits` caracteres) a uno conocido, se usa el conocido.
    2. Si no valida, se prueba una sola sustitución en la parte numérica/homoclave que haga
       valido el dígito verificador. Las letras del nombre solo se corrigen contra RFC conocidos.
    Hay RFC antiguos con dígito verificador inválido, por eso un RFC inválido no se descarta.
    """
    rfc = re.sub(r"[\s\-]", "", token.upper())
    for item in known:
        if similar(rfc, item, max_edits):
            return item.upper(), is_valid_rfc(item), 0 if rfc == item.upper() else 1
    if is_valid_rfc(rfc):
        return rfc, True, 0
    first_free = max(len(rfc) - 9, 0)
    candidates = []
    for index in range(first_free, len(rfc)):
        for replacement in _CONFUSABLE.get(rfc[index], ""):
            text = rfc[:index] + replacement + rfc[index + 1:]
            if is_valid_rfc(text):
                candidates.append(text)
    if len(candidates) == 1:
        return candidates[0], True, 1
    return rfc, False, 0


def similar(a: str | None, b: str | None, tolerance: int = 2) -> bool:
    """Indica si dos RFC difieren en a lo mucho `tolerance` caracteres (confusiones de OCR)."""
    x, y = (a or "").upper().replace(" ", ""), (b or "").upper().replace(" ", "")
    if not x or not y or len(x) != len(y):
        return False
    return sum(1 for p, q in zip(x, y) if p != q) <= tolerance


def find_rfcs(text: str, known: tuple[str, ...] = ()) -> list[dict]:
    """Busca RFC en un texto (con guiones/espacios y errores de OCR) y los corrige."""
    found: dict[str, dict] = {}
    for line_index, line in enumerate(text.splitlines()):
        for match in _TOKEN_RE.finditer(line):
            raw = "".join(match.groups())
            rfc, valid, edits = correct_rfc(raw, known)
            if len(rfc) not in (12, 13):
                continue
            if not valid and edits == 0 and not _valid_date(re.sub(r"[OIL SBGDQ]", "0", rfc[-9:-3])):
                continue
            start, end = match.start(), match.end()
            piped = line[max(0, start - 1):start] == "|" and line[end:end + 1] == "|"
            entry = found.setdefault(rfc, {"rfc": rfc, "valido": valid, "ediciones": edits, "veces": 0,
                                           "primera_linea": line_index, "lineas": [], "entre_barras": True})
            entry["veces"] += 1
            entry["lineas"].append(line_index)
            entry["entre_barras"] = entry["entre_barras"] and piped
    return list(found.values())
