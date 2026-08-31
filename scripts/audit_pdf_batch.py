from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.classification import classify_document
from app.extraction import RFC_RE, extract_invoice_fields


def serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def inspect_pdf(path: Path, root: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    row: dict[str, Any] = {
        "archivo": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest,
        "paginas": 0,
        "cifrado": False,
        "paginas_con_texto": 0,
        "caracteres_texto": 0,
        "naturaleza": "desconocida",
        "clasificacion_preliminar": "desconocido",
        "confianza_clasificacion": 0.0,
        "reglas_coincidentes": "",
        "rfc_emisor_propuesto": None,
        "rfc_candidatos": "",
        "uuid_propuesto": None,
        "fecha_propuesta": None,
        "subtotal_propuesto": None,
        "iva_propuesto": None,
        "total_propuesto": None,
        "error": None,
    }
    try:
        reader = PdfReader(path)
        row["cifrado"] = bool(reader.is_encrypted)
        if reader.is_encrypted and not reader.decrypt(""):
            row["error"] = "PDF cifrado con contrasena"
            return row
        row["paginas"] = len(reader.pages)

        page_texts = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n".join(page_texts).strip()
        chars_by_page = [len(text.strip()) for text in page_texts]
        row["paginas_con_texto"] = sum(chars >= 40 for chars in chars_by_page)
        row["caracteres_texto"] = len(full_text)

        if row["paginas"] and row["paginas_con_texto"] == row["paginas"]:
            row["naturaleza"] = "digital_texto"
        elif row["paginas_con_texto"]:
            row["naturaleza"] = "mixto"
        else:
            row["naturaleza"] = "escaneado_imagen"

        classification = classify_document(full_text)
        row["clasificacion_preliminar"] = classification.type
        row["confianza_clasificacion"] = classification.confidence
        row["reglas_coincidentes"] = ";".join(classification.matched_rules)

        fields = extract_invoice_fields(full_text)
        rfc_candidates = list(dict.fromkeys(match.upper() for match in RFC_RE.findall(full_text)))
        row.update(
            {
                "rfc_emisor_propuesto": fields.get("rfc_emisor"),
                "rfc_candidatos": ";".join(rfc_candidates),
                "uuid_propuesto": serialize(fields.get("uuid_fiscal")),
                "fecha_propuesta": serialize(fields.get("fecha_emision")),
                "subtotal_propuesto": serialize(fields.get("subtotal")),
                "iva_propuesto": serialize(fields.get("iva")),
                "total_propuesto": serialize(fields.get("total")),
            }
        )
    except Exception as exc:  # Audit must continue and report every broken file.
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita un lote de PDF sin modificar sus fuentes.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted(source.rglob("*.pdf"), key=lambda item: item.name.casefold())
    rows = [inspect_pdf(path, source) for path in paths]

    hash_counts = Counter(row["sha256"] for row in rows)
    for row in rows:
        row["duplicado_binario"] = hash_counts[row["sha256"]] > 1

    csv_path = output / "inventario.csv"
    json_path = output / "inventario.json"
    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "archivos": len(rows),
        "paginas": sum(row["paginas"] for row in rows),
        "cifrados": sum(bool(row["cifrado"]) for row in rows),
        "con_error": sum(bool(row["error"]) for row in rows),
        "duplicados_binarios": sum(bool(row["duplicado_binario"]) for row in rows),
        "naturaleza": dict(Counter(row["naturaleza"] for row in rows)),
        "clasificacion_preliminar": dict(
            Counter(row["clasificacion_preliminar"] for row in rows)
        ),
    }
    (output / "resumen.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
