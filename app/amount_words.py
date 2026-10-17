"""Importe con letra en español ("CUATRO MIL OCHENTA PESOS 40/100 M.N.") -> Decimal.

El importe con letra es una verificación independiente del total numérico: si ambos
coinciden, el total leído por OCR es casi seguro correcto.
"""

import difflib
import re
import unicodedata
from decimal import Decimal

_UNITS = {
    "UN": 1, "UNO": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4, "CINCO": 5, "SEIS": 6, "SIETE": 7,
    "OCHO": 8, "NUEVE": 9, "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19, "VEINTE": 20, "VEINTIUN": 21,
    "VEINTIUNO": 21, "VEINTIUNA": 21, "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24,
    "VEINTICINCO": 25, "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
    "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60, "SETENTA": 70, "OCHENTA": 80,
    "NOVENTA": 90, "CIEN": 100, "CIENTO": 100, "DOSCIENTOS": 200, "TRESCIENTOS": 300,
    "CUATROCIENTOS": 400, "QUINIENTOS": 500, "SEISCIENTOS": 600, "SETECIENTOS": 700,
    "OCHOCIENTOS": 800, "NOVECIENTOS": 900,
}
_SCALES = {"MIL": 1_000, "MILLON": 1_000_000, "MILLONES": 1_000_000}
_VOCAB = list(_UNITS) + list(_SCALES) + ["Y"]
_CURRENCY = {"PESOS", "PESO", "MXN", "MN", "M", "N"}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.upper())
    return "".join(char for char in text if not unicodedata.combining(char))


def _canonical(word: str) -> str | None:
    if word in _UNITS or word in _SCALES or word == "Y":
        return word
    if len(word) < 3:
        return None
    match = difflib.get_close_matches(word, _VOCAB, n=1, cutoff=0.82)
    return match[0] if match else None


def _value(words: list[str]) -> int | None:
    total = current = 0
    seen = False
    for word in words:
        if word == "Y":
            continue
        if word in _UNITS:
            current += _UNITS[word]
            seen = True
        elif word in _SCALES:
            total += (current or 1) * _SCALES[word]
            current = 0
            seen = True
    return total + current if seen else None


def amounts_in_words(text: str) -> list[Decimal]:
    """Devuelve los importes con letra encontrados en el texto (puede haber varios)."""
    tokens = re.findall(r"[A-Z]+|\d{1,2}\s*/\s*100", _plain(text).replace("\n", " "))
    found: list[Decimal] = []
    run: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        canonical = None if "/" in token else _canonical(token)
        if canonical:
            run.append(canonical)
            index += 1
            continue
        if run:
            # ¿La racha de números termina en PESOS / MXN / M.N.?
            lookahead = tokens[index:index + 3]
            if any(word in _CURRENCY for word in lookahead[:2]) or any("/" in word for word in lookahead):
                value = _value(run)
                if value is not None and value > 0:
                    cents = 0
                    for word in tokens[index:index + 6]:
                        if "/" in word:
                            cents = int(word.split("/")[0])
                            break
                    found.append(Decimal(value) + Decimal(cents) / 100)
            run = []
        index += 1
    return found
