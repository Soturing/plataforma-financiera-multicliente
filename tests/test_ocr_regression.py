"""Regresión de lectura contra la Prueba 1 (50 páginas reales).

Los documentos y la verdad terreno viven en ``data/fixtures_ocr/prueba1`` (fuera de git, política
del repositorio). Sin esa carpeta la prueba se omite.
"""

from pathlib import Path

import pytest

from app.ocr_eval import evaluate, load_dataset, load_qr, read_texts

DATASET = Path(__file__).resolve().parents[1] / "data" / "fixtures_ocr" / "prueba1"

# Pisos de acierto sobre OCR de imagen (PaddleOCR tiny) + QR del SAT. Solo deben subir.
FLOORS = {
    "proveedor": 0.70, "rfc": 0.75, "folio": 0.78, "fecha": 0.70,
    "subtotal": 0.65, "iva": 0.70, "total": 0.78, "tipo": 0.92,
}


@pytest.mark.skipif(not (DATASET / "verdad.json").exists(), reason="banco de pruebas local no disponible")
def test_reading_accuracy_does_not_regress():
    data = load_dataset(DATASET)
    result = evaluate(read_texts(DATASET, "tiny"), data["verdad"], own=data["propios"], qr=load_qr(DATASET))

    below = {
        field: f"{hits}/{total}"
        for field, (hits, total) in result["hits"].items()
        if total and hits / total < FLOORS[field]
    }
    assert not below, f"campos por debajo del piso: {below}"
