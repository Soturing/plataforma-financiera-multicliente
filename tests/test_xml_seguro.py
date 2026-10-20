import io
import zipfile

import pytest

from app import xml_seguro
from app.errors import DomainError
from app.provider_catalog import parse_provider_file

BOMBA = b"""<?xml version="1.0"?>
<!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>
<r>&b;</r>"""


def _xlsx(partes: dict[str, bytes]) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as archivo:
        for nombre, contenido in partes.items():
            archivo.writestr(nombre, contenido)
    return salida.getvalue()


def test_rechaza_doctype_y_entidades():
    with pytest.raises(DomainError, match="declaración XML"):
        xml_seguro.parsear(BOMBA)


def test_parsea_xml_normal():
    assert xml_seguro.parsear(b"<r><a>1</a></r>").find("a").text == "1"


def test_rechaza_bomba_zip(monkeypatch):
    monkeypatch.setattr(xml_seguro, "MAX_XLSX_DESCOMPRIMIDO", 1024)
    with pytest.raises(DomainError, match="demasiado grande"):
        xml_seguro.verificar_xlsx(_xlsx({"xl/workbook.xml": b"0" * 4096}))


def test_rechaza_lo_que_no_es_zip():
    with pytest.raises(DomainError, match="no es un XLSX"):
        xml_seguro.verificar_xlsx(b"no soy un zip")


def test_el_catalogo_de_proveedores_rechaza_entidades_en_el_xlsx():
    data = _xlsx({"xl/sharedStrings.xml": BOMBA, "xl/workbook.xml": b"<w/>", "xl/_rels/workbook.xml.rels": b"<r/>"})
    with pytest.raises(DomainError, match="declaración XML"):
        parse_provider_file("proveedores.xlsx", data)


def test_rechaza_un_doctype_escondido_tras_un_comentario_largo():
    """Antes sólo se miraban los primeros 8 KB: un relleno largo esquivaba la comprobación."""
    relleno = b"<!--" + b"x" * 20000 + b"-->"
    with pytest.raises(DomainError, match="declaración XML"):
        xml_seguro.parsear(b"<?xml version='1.0'?>" + relleno + b"<!DOCTYPE r [<!ENTITY a 'b'>]><r>&a;</r>")


def test_rechaza_utf16_que_escondia_el_doctype_a_la_busqueda_de_bytes():
    carga = "<?xml version='1.0' encoding='UTF-16'?><!DOCTYPE r [<!ENTITY a 'b'>]><r>&a;</r>".encode("utf-16")
    with pytest.raises(DomainError, match="UTF-8"):
        xml_seguro.parsear(carga)
