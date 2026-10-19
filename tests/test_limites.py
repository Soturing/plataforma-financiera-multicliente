import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

import app.main as principal
from app.errors import DomainError
from app.limite_tasa import LimitadorVentana, ip_del_cliente
from app.storage import read_limited


class Reloj:
    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora


def test_el_limitador_bloquea_al_pasar_el_maximo_y_se_libera_con_la_ventana():
    reloj = Reloj()
    limitador = LimitadorVentana(2, ventana=60, reloj=reloj)
    assert limitador.permitir("a") == (True, 0)
    assert limitador.permitir("a") == (True, 0)
    permitido, espera = limitador.permitir("a")
    assert permitido is False and 1 <= espera <= 61
    # Otra IP no se ve afectada.
    assert limitador.permitir("b")[0] is True
    reloj.ahora += 61
    assert limitador.permitir("a")[0] is True


def test_la_ip_ignora_x_forwarded_for_sin_proxy_confiable():
    assert ip_del_cliente("10.0.0.5", "1.2.3.4", proxy_confiable=False) == "10.0.0.5"
    assert ip_del_cliente(None, None, proxy_confiable=False) == "desconocido"


def test_con_proxy_confiable_se_usa_la_ultima_entrada():
    # Caddy añade la IP real al final; lo que mande el cliente va antes y no cuenta.
    assert ip_del_cliente("172.18.0.2", "9.9.9.9, 203.0.113.7", proxy_confiable=True) == "203.0.113.7"
    assert ip_del_cliente("172.18.0.2", None, proxy_confiable=True) == "172.18.0.2"


def _archivo(tamano: int) -> UploadFile:
    return UploadFile(file=io.BytesIO(b"x" * tamano), filename="catalogo.xlsx")


def test_read_limited_lee_archivos_dentro_del_limite():
    contenido = asyncio.run(read_limited(_archivo(3 * 1024 * 1024), 4 * 1024 * 1024, "grande"))
    assert len(contenido) == 3 * 1024 * 1024


def test_read_limited_rechaza_con_413_sin_leer_todo():
    with pytest.raises(DomainError) as error:
        asyncio.run(read_limited(_archivo(5 * 1024 * 1024), 2 * 1024 * 1024, "demasiado grande"))
    assert error.value.status_code == 413


def test_la_app_responde_429_al_superar_el_limite_de_acceso(monkeypatch):
    monkeypatch.setattr(principal._ajustes, "limite_acceso_por_minuto", 2)
    monkeypatch.setattr(principal, "_limite_acceso", LimitadorVentana(2))
    cliente = TestClient(principal.app)
    estados = [cliente.get("/auth/entrar", follow_redirects=False).status_code for _ in range(3)]
    assert 429 not in estados[:2]
    assert estados[2] == 429
    respuesta = cliente.get("/auth/entrar", follow_redirects=False)
    assert respuesta.headers["Retry-After"].isdigit()
    # Las cabeceras de seguridad también viajan en el 429.
    assert respuesta.headers["X-Content-Type-Options"] == "nosniff"
