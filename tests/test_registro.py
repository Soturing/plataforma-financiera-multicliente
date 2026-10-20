import json
import logging

from fastapi.testclient import TestClient

from app import registro
from app.main import app


def _registro(mensaje="hola", **extra):
    r = logging.LogRecord("facturas.prueba", logging.WARNING, __file__, 1, mensaje, (), None)
    r.__dict__.update(extra)
    return r


def test_el_formato_json_lleva_id_de_peticion_y_campos_extra():
    token = registro.peticion_id.set("abc12345-req")
    try:
        datos = json.loads(registro.FormatoJson().format(_registro("Falló %s".replace("%s", "x"), ruta="/api/v1/x", ms=12)))
    finally:
        registro.peticion_id.reset(token)
    assert datos["peticion_id"] == "abc12345-req"
    assert datos["nivel"] == "WARNING" and datos["logger"] == "facturas.prueba"
    assert datos["ruta"] == "/api/v1/x" and datos["ms"] == 12
    assert datos["ts"].endswith("+00:00")


def test_sin_peticion_no_se_inventa_el_id():
    assert "peticion_id" not in json.loads(registro.FormatoJson().format(_registro()))


def test_la_excepcion_va_en_su_propio_campo():
    try:
        1 / 0
    except ZeroDivisionError:
        import sys
        r = _registro("error")
        r.exc_info = sys.exc_info()
    assert "ZeroDivisionError" in json.loads(registro.FormatoJson().format(r))["excepcion"]


def test_solo_se_acepta_un_id_entrante_con_forma_segura():
    assert registro.nuevo_peticion_id("req-1234.abcd") == "req-1234.abcd"
    for malo in (None, "", "corto", "con espacios 12345678", "a" * 65, "id\r\nSet-Cookie: x"):
        generado = registro.nuevo_peticion_id(malo)
        assert generado != malo and len(generado) == 32


def test_la_respuesta_devuelve_el_id_de_la_peticion():
    cliente = TestClient(app)
    assert cliente.get("/", headers={"X-Request-ID": "mi-peticion-0001"}).headers["X-Request-ID"] == "mi-peticion-0001"
    sin_id = cliente.get("/").headers["X-Request-ID"]
    assert len(sin_id) == 32
    ajeno = cliente.get("/", headers={"X-Request-ID": "no valido por espacios"}).headers["X-Request-ID"]
    assert ajeno != "no valido por espacios" and len(ajeno) == 32


def test_configurar_es_idempotente_y_cambia_de_formato():
    raiz = logging.getLogger()
    antes = len(raiz.handlers)
    registro.configurar(True)
    registro.configurar(True)
    propios = [h for h in raiz.handlers if getattr(h, "_facturas", False)]
    assert len(propios) == 1 and isinstance(propios[0].formatter, registro.FormatoJson)
    registro.configurar(False)
    propios = [h for h in raiz.handlers if getattr(h, "_facturas", False)]
    assert len(propios) == 1 and not isinstance(propios[0].formatter, registro.FormatoJson)
    assert len(raiz.handlers) <= antes + 1
