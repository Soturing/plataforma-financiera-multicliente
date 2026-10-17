"""Evaluación de la lectura de facturas contra una verdad terreno local.

La verdad terreno y los textos viven en una carpeta fuera de git (p. ej.
``data/fixtures_ocr/prueba1``); este módulo solo contiene la lógica de comparación.
"""

import difflib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from app.classification import classify_document
from app.extraction import extract_invoice_fields

FIELDS = ("proveedor", "rfc", "folio", "fecha", "subtotal", "iva", "total", "tipo")
TYPE_MAP = {"F": {"factura_fiscal"}, "R": {"remision", "nota_venta"}, "T": {"ticket_compra", "nota_venta"}}


def plain(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").upper())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", text).split())


def squash(value: Any) -> str:
    return plain(value).replace(" ", "")


def name_matches(truth: Any, got: Any) -> bool:
    a, b = plain(truth), plain(got)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    ta = {token for token in a.split() if len(token) > 2}
    tb = {token for token in b.split() if len(token) > 2}
    if ta and len(ta & tb) / len(ta) >= 0.6:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "", "None") else None
    except Exception:
        return None


def money_equal(a: Any, b: Any) -> bool:
    x, y = money(a), money(b)
    return x is not None and y is not None and abs(x - y) <= Decimal("0.01")


def load_dataset(root: Path) -> dict[str, Any]:
    root = Path(root)
    return {
        "verdad": {int(k): v for k, v in json.load(open(root / "verdad.json", encoding="utf-8")).items()},
        "propios": json.load(open(root / "propios.json", encoding="utf-8")) if (root / "propios.json").exists() else {},
        "root": root,
    }


def read_texts(root: Path, source: str) -> dict[int, str]:
    folder = Path(root) / f"texto_{source}"
    return {int(path.stem[1:]): path.read_text(encoding="utf-8") for path in sorted(folder.glob("p*.txt"))}


def load_qr(root: Path) -> dict[int, dict[str, Any]]:
    path = Path(root) / "qr.json"
    return {int(k): v for k, v in json.load(open(path, encoding="utf-8")).items()} if path.exists() else {}


def evaluate(
    texts: dict[int, str],
    truth: dict[int, dict[str, Any]],
    reader: Callable[[int, str], dict[str, Any]] | None = None,
    own: dict[str, Any] | None = None,
    qr: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compara los campos leídos con la verdad terreno página por página."""
    own = own or {}
    qr = qr or {}
    hits = {field: [0, 0] for field in FIELDS}
    pages: dict[int, dict[str, Any]] = {}
    for page, real in sorted(truth.items()):
        text = texts.get(page, "")
        if reader is not None:
            got = reader(page, text)
        else:
            got = extract_invoice_fields(
                text, own_rfcs=own.get("rfcs", ()), own_names=own.get("nombres", ()), qr=qr.get(page),
            )
        classification = classify_document(text, has_sat_qr=page in qr)
        checks = {
            "proveedor": (real["emisor"], name_matches(real["emisor"], got.get("proveedor_propuesto"))),
            "rfc": (real["rfc_emisor"], squash(real["rfc_emisor"]) == squash(got.get("rfc_emisor"))),
            "folio": (real["folio"], bool(got.get("folio")) and got.get("folio_origen") != "fecha"
                      and squash(real["folio"]) in squash(got.get("folio"))),
            "fecha": (real["fecha"], str(got.get("fecha_emision")) == real["fecha"]),
            "subtotal": (real["subtotal"], money_equal(got.get("subtotal"), real["subtotal"])),
            "iva": (real["iva"], money_equal(got.get("iva"), real["iva"])),
            "total": (real["total"], money_equal(got.get("total"), real["total"])),
            "tipo": (real["tipo"] if real["tipo"] in TYPE_MAP else None, classification.type in TYPE_MAP.get(real["tipo"], set())),
        }
        row = {}
        for field, (expected, ok) in checks.items():
            if expected is None:
                continue
            hits[field][1] += 1
            hits[field][0] += bool(ok)
            row[field] = bool(ok)
        pages[page] = {"ok": row, "got": got, "tipo": classification.type}
    return {"hits": hits, "pages": pages}


def format_summary(result: dict[str, Any]) -> str:
    return "  ".join(
        f"{field}: {a}/{b} ({100 * a / b:.0f}%)" for field, (a, b) in result["hits"].items() if b
    )
