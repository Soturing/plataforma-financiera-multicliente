"""Una foto parecida a varios documentos previos no debe tronar el guardado del OCR.

Antes se insertaba una validación POSIBLE_DUPLICADO por cada parecido y la restricción
validaciones_interpretacion_id_codigo_key rechazaba la segunda.
"""

from psycopg.rows import dict_row

from app.ocr.base import OcrDocument
from app.ocr_processing import persist_ocr_result
from apoyo_db import conexion_pruebas

TICKET = """
REMISION
PROVEEDOR: PROVEEDOR FICTICIO ALFA
FECHA: {fecha}
FOLIO: {folio}
TOTAL 3360.00
"""


def _nueva_factura(conn, n: int):
    return conn.execute(
        """
        INSERT INTO core.facturas (
            sucursal_id, estado, archivo_url, archivo_nombre, archivo_mime,
            archivo_sha256, creada_por
        )
        SELECT id, 'ocr_procesando', %s, %s, 'text/plain', %s, 'pytest-parecidos'
        FROM catalog.sucursales WHERE clave = 'DEMO-A'
        RETURNING id
        """,
        (f"pytest://parecido-{n}", f"parecido-{n}.txt", f"{n:064x}"),
    ).fetchone()["id"]


def _ocr(conn, invoice_id, fecha: str, folio: str):
    document = OcrDocument(
        text=TICKET.format(fecha=fecha, folio=folio), lines=[], confidence=0.9, raw={},
        provider="pytest", model="synthetic", duration_ms=1,
    )
    persist_ocr_result(conn, invoice_id, document)


def test_varios_parecidos_quedan_en_una_sola_validacion():
    with conexion_pruebas(row_factory=dict_row) as conn:
        # Sólo se comparan documentos de un proveedor identificado en el catálogo.
        conn.execute(
            "INSERT INTO catalog.proveedores (nombre_legal, nombre_normalizado) VALUES (%s, %s)",
            ("PROVEEDOR FICTICIO ALFA", "PROVEEDOR FICTICIO ALFA"),
        )
        for n, fecha, folio in ((1, "12/08/2026", "R-101"), (2, "13/08/2026", "R-102")):
            _ocr(conn, _nueva_factura(conn, n), fecha, folio)

        tercera = _nueva_factura(conn, 3)
        _ocr(conn, tercera, "14/08/2026", "R-103")

        estado = conn.execute("SELECT estado::text FROM core.facturas WHERE id = %s", (tercera,)).fetchone()["estado"]
        parecidos = conn.execute(
            "SELECT mensaje FROM core.validaciones WHERE factura_id = %s AND codigo = 'POSIBLE_DUPLICADO'",
            (tercera,),
        ).fetchall()
        conn.rollback()

    assert estado == "requiere_revision"
    assert len(parecidos) == 1
    assert "parecido-1.txt" in parecidos[0]["mensaje"]
    assert "parecido-2.txt" in parecidos[0]["mensaje"]
