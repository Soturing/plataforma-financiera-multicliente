import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader, PdfWriter

from app.errors import DomainError


@dataclass(frozen=True)
class SplitPage:
    number: int
    path: Path
    sha256: str


def _read_pdf(source: Path) -> PdfReader:
    try:
        reader = PdfReader(source)
    except Exception as exc:
        raise DomainError("El archivo no es un PDF válido o está dañado.", 422) from exc

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:
            unlocked = 0
        if not unlocked:
            raise DomainError("El PDF está protegido con contraseña.", 422)
    return reader


def pdf_page_count(source: Path) -> int:
    reader = _read_pdf(source)
    page_count = len(reader.pages)
    if page_count == 0:
        raise DomainError("El PDF no contiene páginas.", 422)
    return page_count


def split_pdf(source: Path, destination_root: Path, batch_id: UUID, max_pages: int) -> list[SplitPage]:
    reader = _read_pdf(source)

    page_count = len(reader.pages)
    if page_count == 0:
        raise DomainError("El PDF no contiene páginas.", 422)
    if page_count > max_pages:
        raise DomainError(f"El PDF tiene {page_count} páginas; el máximo permitido es {max_pages}.", 422)

    batch_dir = destination_root / "lotes" / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=False)
    pages: list[SplitPage] = []
    try:
        for number, page in enumerate(reader.pages, start=1):
            output_path = batch_dir / f"pagina-{number:04d}.pdf"
            writer = PdfWriter()
            writer.add_page(page)
            with output_path.open("wb") as stream:
                writer.write(stream)
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            pages.append(SplitPage(number=number, path=output_path, sha256=digest))
    except Exception:
        for generated in pages:
            generated.path.unlink(missing_ok=True)
        batch_dir.rmdir()
        raise
    return pages
