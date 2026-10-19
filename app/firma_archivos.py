"""Firma real de los archivos subidos (roadmap §3.6.4, hallazgo 5 de la auditoría).

El tipo MIME y la extensión los manda el cliente; aquí se comprueba el contenido. Sólo mira
los primeros bytes: no sustituye a un antivirus (ClamAV queda pendiente de decisión), pero
impide pasar por factura un ejecutable, un HTML o un ZIP con otro nombre.
"""
from __future__ import annotations

from app.errors import DomainError

CABECERA_MINIMA = 16  # bytes necesarios para reconocer cualquier firma de abajo
_BOM_UTF8 = b"\xef\xbb\xbf"

# Tipo detectado -> extensión con la que se guarda (nunca la que mande el cliente).
EXTENSION_POR_TIPO = {
    "pdf": ".pdf",
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "xml": ".xml",
    "xlsx": ".xlsx",
}

TIPO_POR_MIME = {
    "application/pdf": "pdf",
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


def detectar(cabecera: bytes) -> str | None:
    """Tipo reconocido por la firma de los primeros bytes, o None."""
    if b"%PDF-" in cabecera[:1024]:
        return "pdf"
    if cabecera.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return "webp"
    if cabecera.startswith(b"PK\x03\x04"):
        return "xlsx"  # un XLSX es un ZIP; el análisis posterior valida que lo sea de verdad
    if cabecera.removeprefix(_BOM_UTF8).lstrip().startswith(b"<"):
        return "xml"
    return None


def es_texto_plano(cabecera: bytes) -> bool:
    """CSV/TSV: sin bytes nulos ni firmas binarias conocidas."""
    return b"\x00" not in cabecera and detectar(cabecera) in (None, "xml")


def verificar(cabecera: bytes, esperado: str) -> str:
    """Comprueba que el contenido corresponde al tipo declarado ('pdf', 'jpeg'… o 'texto').

    Devuelve el tipo detectado; si no corresponde, 415 con un mensaje que no revela la firma.
    """
    if esperado == "texto":
        if not es_texto_plano(cabecera):
            raise DomainError("El contenido del archivo no corresponde a un CSV o TSV.", 415)
        return "texto"
    detectado = detectar(cabecera)
    if detectado != esperado:
        raise DomainError("El contenido del archivo no corresponde a su tipo.", 415)
    return detectado


def tipo_esperado(tipo_mime: str | None, extension: str) -> str | None:
    """Tipo que debe tener el contenido según lo que declara el cliente (MIME o extensión .xml)."""
    if tipo_mime in TIPO_POR_MIME:
        return TIPO_POR_MIME[tipo_mime]
    if extension == ".xml":  # application/octet-stream con extensión .xml
        return "xml"
    if extension == ".xlsx":
        return "xlsx"
    return None
