"""Lectura de XML y XLSX recibidos del usuario (roadmap §3.6.3).

`xml.etree` en Python 3.12+ no resuelve entidades externas y su expat limita la
expansión de entidades; además, un CFDI o un XLSX legítimo nunca declara DOCTYPE ni
ENTITY, así que se rechazan antes de parsear. Un XLSX es un ZIP: se comprueba el
tamaño descomprimido declarado antes de leerlo, contra bombas zip.
"""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET  # nosec B405
# Motivo: sólo se parsea tras `rechazar_declaraciones`

from app.errors import DomainError

MAX_XLSX_DESCOMPRIMIDO = 50 * 1024 * 1024
MAX_PARTES_XLSX = 2000


Element = ET.Element
ParseError = ET.ParseError

# UTF-16/UTF-32 no son CFDI y esconderían un DOCTYPE a una búsqueda de bytes.
_BOM_NO_UTF8 = (b"\xff\xfe", b"\xfe\xff")


def rechazar_declaraciones(payload: bytes) -> None:
    """Rechaza DOCTYPE y ENTITY en todo el contenido, no sólo al principio: un comentario largo
    antes de la declaración no debe esquivar la comprobación."""
    if payload.startswith(_BOM_NO_UTF8):
        raise DomainError("El archivo XML debe estar codificado en UTF-8.", 422)
    mayusculas = payload.upper()
    if b"<!DOCTYPE" in mayusculas or b"<!ENTITY" in mayusculas:
        raise DomainError("El archivo contiene una declaración XML no permitida.", 422)


def parsear(payload: bytes) -> ET.Element:
    rechazar_declaraciones(payload)
    return ET.fromstring(payload)  # nosec B314
    # Motivo: declaraciones rechazadas arriba; expat de 3.12 no resuelve externas


def verificar_xlsx(data: bytes) -> None:
    """Falla si el ZIP no es válido o si descomprimido supera el límite."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archivo:
            partes = archivo.infolist()
    except zipfile.BadZipFile as exc:
        raise DomainError("El archivo no es un XLSX válido.", 422) from exc
    if len(partes) > MAX_PARTES_XLSX or sum(p.file_size for p in partes) > MAX_XLSX_DESCOMPRIMIDO:
        raise DomainError("El XLSX es demasiado grande una vez descomprimido.", 422)
