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
