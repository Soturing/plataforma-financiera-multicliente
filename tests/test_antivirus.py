"""Antivirus: protocolo de clamd, modos y limpieza. Un clamd falso en un hilo evita depender de ClamAV en el CI.

La prueba con ClamAV de verdad (EICAR) corre sólo si `CLAMD_PRUEBAS=host:puerto` apunta a un clamd.
"""
import asyncio
import os
import socket
import struct
import threading
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from app.antivirus import AntivirusNoDisponible, _escanear_flujo, escanear_archivo, escanear_bytes
from app.config import Settings
from app.errors import DomainError
from app.storage import save_upload

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"


class ClamdFalso:
    """Servidor TCP mínimo que habla INSTREAM: contesta FOUND si el contenido incluye EICAR."""

    def __init__(self, respuesta: bytes | None = None):
        self.respuesta = respuesta
        self.recibido = b""
        self.comando = b""
        self.trozos = 0
        self._servidor = socket.socket()
        self._servidor.bind(("127.0.0.1", 0))
        self._servidor.listen(5)
        self.puerto = self._servidor.getsockname()[1]
        threading.Thread(target=self._atender, daemon=True).start()

    def _leer(self, conexion, n):
        datos = b""
        while len(datos) < n:
            parte = conexion.recv(n - len(datos))
            if not parte:
                raise ConnectionError
            datos += parte
        return datos

    def _atender(self):
        while True:
            try:
                conexion, _ = self._servidor.accept()
            except OSError:
                return
            with conexion:
                try:
                    self.comando = self._leer(conexion, len(b"zINSTREAM\0"))
                    cuerpo = b""
                    while (largo := struct.unpack("!I", self._leer(conexion, 4))[0]):
                        cuerpo += self._leer(conexion, largo)
                        self.trozos += 1
                    self.recibido = cuerpo
                    if self.respuesta is not None:
                        conexion.sendall(self.respuesta)
                    elif b"EICAR-STANDARD" in cuerpo:
                        conexion.sendall(b"stream: Win.Test.EICAR_HDB-1 FOUND\0")
                    else:
                        conexion.sendall(b"stream: OK\0")
                except (ConnectionError, OSError):
                    pass

    def cerrar(self):
        self._servidor.close()


@pytest.fixture
def clamd():
    servidor = ClamdFalso()
    yield servidor
    servidor.cerrar()


def _ajustes(tmp_path, modo, puerto):
    return Settings(
        database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path / "subidas", antivirus_modo=modo,
        antivirus_host="127.0.0.1", antivirus_puerto=puerto, antivirus_timeout=3, _env_file=None,
    )


def _puerto_cerrado() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _subir(ajustes, contenido=PDF, nombre="factura.pdf", tipo="application/pdf"):
    import io
    archivo = UploadFile(file=io.BytesIO(contenido), filename=nombre, headers=Headers({"content-type": tipo}))
    return asyncio.run(save_upload(archivo, ajustes))


def test_el_protocolo_envia_instream_en_trozos_y_cierra_con_longitud_cero(clamd):
    grande = os.urandom(200_000)
    assert _escanear_flujo(iter([grande[:100_000], grande[100_000:]]), "127.0.0.1", clamd.puerto, 3) is None
    assert clamd.comando == b"zINSTREAM\0" and clamd.recibido == grande and clamd.trozos == 2


def test_un_archivo_limpio_se_guarda(tmp_path, clamd):
    ruta, _, tamano = _subir(_ajustes(tmp_path, "obligatorio", clamd.puerto))
    assert ruta.read_bytes() == PDF and tamano == len(PDF)
    assert clamd.recibido == PDF


def test_un_archivo_infectado_se_rechaza_y_no_queda_en_disco(tmp_path, clamd):
    with pytest.raises(DomainError) as error:
        _subir(_ajustes(tmp_path, "opcional", clamd.puerto), contenido=PDF + EICAR)
    assert error.value.status_code == 422 and "malicioso" in error.value.message
    assert list((tmp_path / "subidas").iterdir()) == []


def test_obligatorio_sin_servicio_rechaza_y_no_deja_archivo(tmp_path):
    with pytest.raises(DomainError) as error:
        _subir(_ajustes(tmp_path, "obligatorio", _puerto_cerrado()))
    assert error.value.status_code == 503
    assert list((tmp_path / "subidas").iterdir()) == []


def test_opcional_sin_servicio_acepta_con_aviso(tmp_path, caplog):
    ruta, _, _ = _subir(_ajustes(tmp_path, "opcional", _puerto_cerrado()))
    assert ruta.is_file()
    assert any("sin escanear" in r.getMessage() for r in caplog.records)


def test_apagado_no_se_conecta(tmp_path):
    ruta, _, _ = _subir(_ajustes(tmp_path, "apagado", _puerto_cerrado()))
    assert ruta.is_file()


def test_una_respuesta_de_error_de_clamd_cuenta_como_servicio_no_disponible(tmp_path):
    servidor = ClamdFalso(respuesta=b"INSTREAM size limit exceeded. ERROR\0")
    try:
        with pytest.raises(AntivirusNoDisponible):
            _escanear_flujo(iter([PDF]), "127.0.0.1", servidor.puerto, 3)
        with pytest.raises(DomainError) as error:
            _subir(_ajustes(tmp_path, "obligatorio", servidor.puerto))
        assert error.value.status_code == 503
    finally:
        servidor.cerrar()


def test_los_archivos_en_memoria_tambien_se_escanean(tmp_path, clamd):
    ajustes = _ajustes(tmp_path, "obligatorio", clamd.puerto)
    asyncio.run(escanear_bytes(b"a,b\n1,2\n", ajustes, "catalogo.csv"))
    with pytest.raises(DomainError):
        asyncio.run(escanear_bytes(EICAR, ajustes, "catalogo.csv"))


@pytest.mark.skipif(not os.environ.get("CLAMD_PRUEBAS"), reason="Define CLAMD_PRUEBAS=host:puerto para probar con ClamAV real")
def test_clamav_real_detecta_eicar_y_deja_pasar_un_pdf(tmp_path):
    # EICAR es una firma por huella: sólo se detecta si el archivo es exactamente la cadena de prueba.
    host, _, puerto = os.environ["CLAMD_PRUEBAS"].partition(":")
    ajustes = _ajustes(tmp_path, "obligatorio", int(puerto))
    ajustes.antivirus_host = host
    ruta, _, _ = _subir(ajustes)
    assert ruta.is_file()
    with pytest.raises(DomainError) as error:
        asyncio.run(escanear_bytes(EICAR, ajustes, "catalogo.csv"))
    assert error.value.status_code == 422
    infectado = tmp_path / "eicar.com"
    infectado.write_bytes(EICAR)
    with pytest.raises(DomainError):
        asyncio.run(escanear_archivo(infectado, ajustes))
