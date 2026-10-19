import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import Settings
from app.errors import DomainError
from app.firma_archivos import EXTENSION_POR_TIPO, tipo_esperado, verificar


async def read_limited(file: UploadFile, limit: int, message: str) -> bytes:
    """Lee el archivo por partes y se detiene en cuanto supera `limit` (413), sin cargarlo entero."""
    partes: list[bytes] = []
    total = 0
    try:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise DomainError(message, 413)
            partes.append(chunk)
    finally:
        await file.close()
    return b"".join(partes)


async def save_upload(file: UploadFile, settings: Settings) -> tuple[Path, str, int]:
    extension = Path(file.filename or "factura").suffix.lower()
    xml_fallback = extension == ".xml" and file.content_type == "application/octet-stream"
    if file.content_type not in settings.allowed_mime_types and not xml_fallback:
        raise DomainError("Formato no permitido. Usa JPG, PNG, WEBP, PDF o XML CFDI.", 415)

    if file.content_type in {"application/xml", "text/xml"} and extension != ".xml":
        raise DomainError("El archivo XML debe tener extensión .xml.", 415)
    primer = await file.read(1024 * 1024)
    if primer:
        # El contenido manda: la extensión con la que se guarda sale del tipo detectado,
        # no del nombre que envía el cliente.
        try:
            detectado = verificar(primer, tipo_esperado(file.content_type, extension) or "")
        except DomainError:
            await file.close()
            raise
        extension = EXTENSION_POR_TIPO[detectado]
    destination = settings.upload_dir / f"{uuid4()}{extension}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0

    try:
        with destination.open("wb") as output:
            chunk = primer
            while chunk:
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise DomainError(
                        f"El archivo supera el límite de {settings.max_upload_bytes // (1024 * 1024)} MB."
                    )
                digest.update(chunk)
                output.write(chunk)
                chunk = await file.read(1024 * 1024)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if size == 0:
        destination.unlink(missing_ok=True)
        raise DomainError("El archivo está vacío.")

    return destination, digest.hexdigest(), size
