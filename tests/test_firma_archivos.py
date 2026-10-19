import asyncio
import io

import pytest
from starlette.datastructures import UploadFile

from app.config import Settings
from app.errors import DomainError
from app.firma_archivos import detectar, es_texto_plano, verificar
from app.storage import save_upload

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 12
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "
ZIP = b"PK\x03\x04" + b"\x00" * 12
EXE = b"MZ\x90\x00\x03\x00\x00\x00"
HTML = b"<html><script>alert(1)</script></html>"


def test_detecta_cada_tipo_por_sus_primeros_bytes():
    assert detectar(PDF) == "pdf"
    assert detectar(JPEG) == "jpeg"
    assert detectar(PNG) == "png"
    assert detectar(WEBP) == "webp"
    assert detectar(ZIP) == "xlsx"
    assert detectar(b"\xef\xbb\xbf  <?xml version='1.0'?><a/>") == "xml"
    assert detectar(EXE) is None
    assert detectar(b"") is None


def test_un_ejecutable_o_un_zip_no_pasan_por_pdf_ni_imagen():
    for contenido in (EXE, ZIP, b"texto cualquiera"):
        for esperado in ("pdf", "jpeg", "png", "webp"):
            with pytest.raises(DomainError) as error:
                verificar(contenido, esperado)
            assert error.value.status_code == 415


def test_un_csv_es_texto_y_un_binario_no():
    assert es_texto_plano(b"nombre,rfc\nCafe,XAXX010101000\n")
    assert not es_texto_plano(EXE + b"\x00\x00")
    assert not es_texto_plano(PNG)
    assert not es_texto_plano(ZIP)


def _subir(tmp_path, nombre, contenido, tipo):
    ajustes = Settings(database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path, _env_file=None)
    archivo = UploadFile(file=io.BytesIO(contenido), filename=nombre, headers={"content-type": tipo})
    return asyncio.run(save_upload(archivo, ajustes))


def test_save_upload_guarda_con_la_extension_del_contenido(tmp_path):
    ruta, _, tamano = _subir(tmp_path, "factura.JPEG", JPEG, "image/jpeg")
    assert ruta.suffix == ".jpg" and tamano == len(JPEG)
    ruta, _, _ = _subir(tmp_path, "otra.pdf", PDF, "application/pdf")
    assert ruta.suffix == ".pdf"


def test_save_upload_ignora_la_extension_que_manda_el_cliente(tmp_path):
    ruta, _, _ = _subir(tmp_path, "factura.html", PNG, "image/png")
    assert ruta.suffix == ".png"


def test_save_upload_rechaza_html_disfrazado_de_imagen_y_no_deja_archivo(tmp_path):
    with pytest.raises(DomainError) as error:
        _subir(tmp_path, "factura.jpg", HTML, "image/jpeg")
    assert error.value.status_code == 415
    assert list(tmp_path.iterdir()) == []


def test_save_upload_rechaza_un_ejecutable_como_pdf(tmp_path):
    with pytest.raises(DomainError) as error:
        _subir(tmp_path, "factura.pdf", EXE, "application/pdf")
    assert error.value.status_code == 415
    assert list(tmp_path.iterdir()) == []


def test_save_upload_acepta_xml_y_xml_con_octet_stream(tmp_path):
    cfdi = b"\xef\xbb\xbf<?xml version='1.0' encoding='UTF-8'?><cfdi:Comprobante/>"
    ruta, _, _ = _subir(tmp_path, "cfdi.xml", cfdi, "application/xml")
    assert ruta.suffix == ".xml"
    ruta, _, _ = _subir(tmp_path, "cfdi2.xml", cfdi, "application/octet-stream")
    assert ruta.suffix == ".xml"


def test_un_archivo_vacio_sigue_dando_el_error_de_vacio(tmp_path):
    with pytest.raises(DomainError) as error:
        _subir(tmp_path, "vacio.pdf", b"", "application/pdf")
    assert "vacío" in error.value.message
    assert list(tmp_path.iterdir()) == []
