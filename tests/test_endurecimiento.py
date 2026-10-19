from fastapi.testclient import TestClient

from app.endurecimiento import (
    CONTENIDO_SEGURIDAD,
    disposicion,
    documentacion_activa,
)
from app.main import app


def test_solo_pdf_e_imagenes_se_muestran_en_linea():
    assert disposicion("application/pdf") == "inline"
    assert disposicion("image/png") == "inline"
    assert disposicion("image/webp") == "inline"
    # Un XML o un tipo desconocido nunca se ejecuta en el navegador.
    assert disposicion("application/xml") == "attachment"
    assert disposicion("text/html") == "attachment"
    assert disposicion("application/octet-stream") == "attachment"


def test_documentacion_solo_en_desarrollo_con_acceso_abierto():
    assert documentacion_activa("development", "abierto") is True
    assert documentacion_activa("development", "seguro") is False
    assert documentacion_activa("produccion", "abierto") is False
    assert documentacion_activa("produccion", "seguro") is False


def test_la_politica_de_contenido_no_permite_scripts_ajenos():
    assert "script-src 'self'" in CONTENIDO_SEGURIDAD
    assert "object-src 'none'" in CONTENIDO_SEGURIDAD
    assert "unsafe-eval" not in CONTENIDO_SEGURIDAD


def test_las_respuestas_llevan_cabeceras_de_seguridad():
    cliente = TestClient(app)
    respuesta = cliente.get("/")
    assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
    assert respuesta.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert respuesta.headers["Content-Security-Policy"] == CONTENIDO_SEGURIDAD
    assert respuesta.headers["Referrer-Policy"] == "same-origin"
