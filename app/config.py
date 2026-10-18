from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Facturación IA"
    environment: str = "development"
    database_url: str
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 200
    # Cola OCR: procesos lectores permanentes. Cada uno carga su propio modelo
    # (cientos de MB de RAM), así que súbalo según la memoria del servidor.
    ocr_workers: int = 1
    # El API levanta el supervisor de workers si nadie está leyendo. En un
    # servidor con servicio propio para los workers, desactívelo.
    ocr_autostart_workers: bool = True
    ocr_lease_seconds: int = 120
    allowed_mime_types: frozenset[str] = frozenset(
        {
            "image/jpeg", "image/png", "image/webp", "application/pdf",
            "application/xml", "text/xml",
        }
    )

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FACTURAS_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
