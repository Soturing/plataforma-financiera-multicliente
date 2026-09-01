from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Facturación IA"
    environment: str = "development"
    database_url: str
    control_database_url: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_identity_provider: str | None = None
    oidc_auth_level_claim: str | None = None
    data_plane_config_dir: Path | None = None
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 40 * 1024 * 1024
    max_pdf_pages: int = 200
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
