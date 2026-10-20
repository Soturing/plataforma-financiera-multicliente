import hashlib
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import Settings
from app.errors import DomainError
from app.firma_archivos import EXTENSION_POR_TIPO, tipo_esperado, verificar


def ruta_para_guardar(path: Path | str, upload_dir: Path) -> str:
    """Valor que se guarda en la base: ruta relativa al directorio de archivos del cliente.

    Así la base no revela la estructura del servidor y el almacenamiento puede cambiar de
    lugar (anfitrión o contenedor) sin reescribir filas. Un archivo fuera de ese directorio
    (datos heredados, pruebas) conserva su ruta tal cual.
    """
    try:
        return Path(path).resolve().relative_to(upload_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def ruta_almacenada(valor: str, upload_dir: Path) -> Path:
    """Ruta real de un archivo guardado: relativa al directorio del cliente, o absoluta si es un dato heredado.

    Quien la use debe seguir comprobando que el resultado queda dentro de `upload_dir`
    (`is_relative_to`): una ruta relativa con `..` se resuelve aquí y esa comprobación la rechaza.
    """
    ruta = Path(valor)
    return (ruta if ruta.is_absolute() else upload_dir / ruta).resolve()


_NOMBRE_PROHIBIDO = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|;]+')


def nombre_seguro(nombre: str | None, defecto: str = "documento", maximo: int = 120) -> str:
    """Nombre de archivo apto para guardar y para `Content-Disposition`.

    Sin directorios, comillas, separadores ni caracteres de control; recortado conservando la extensión.
    """
    base = _NOMBRE_PROHIBIDO.sub("_", (nombre or "").replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    if not base:
        return defecto
    if len(base) > maximo:
        extension = Path(base).suffix[:10]
        base = base[: maximo - len(extension)] + extension
    return base


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
