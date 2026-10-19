from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Facturación IA"
    environment: str = "development"
    database_url: str
    upload_dir: Path = Path("data/uploads")
    max_upload_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 200
    # Límite de peticiones por IP y por minuto (app/limite_tasa.py); 0 lo apaga.
    # `limite_acceso_por_minuto` es el de /auth/*, más estricto contra fuerza bruta.
    limite_peticiones_por_minuto: int = 1200
    limite_acceso_por_minuto: int = 30
    # Detrás del proxy propio (Caddy) la IP real viene en X-Forwarded-For; sin proxy no se confía en ella.
    proxy_confiable: bool = False
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

    # Acceso seguro (docs/seguridad/plan-implementacion.md, fases 2–4).
    # "seguro" (por defecto, D-028): toda ruta de datos exige sesión. "abierto": la app
    # funciona sin sesión como antes; sólo para desarrollo local, con
    # FACTURAS_ACCESO_MODO=abierto escrito a propósito. En producción no se admite.
    acceso_modo: Literal["abierto", "seguro"] = "seguro"
    control_database_url: str | None = None
    app_url: str = "http://127.0.0.1:8010"
    oidc_issuer: str = "http://localhost:8180/realms/facturas"
    # Base para llamadas de servidor a servidor (token, llaves, administración). El
    # navegador sigue usando el issuer público. En producción: la red interna.
    oidc_url_interna: str | None = None
    oidc_client_id: str = "facturas-app"
    oidc_client_secret: str | None = None
    idp_admin_client_id: str = "facturas-control"
    idp_admin_client_secret: str | None = None
    # Identidad de este data plane (D-016): la sesión debe pertenecer a este cliente.
    tenant_clave: str = "GRUPO-DEMO"
    tenant_nombre: str = "Grupo restaurantero demo"
    # Avisos del ciclo de vida (app/seguridad/notificaciones.py). En desarrollo: Mailpit.
    smtp_host: str | None = None
    smtp_port: int = 1025
    smtp_tls: bool = False
    smtp_usuario: str | None = None
    smtp_password: str | None = None
    smtp_remitente: str = "accesos@facturas.localhost"
    # Cookie `Secure`: obligatoria con HTTPS en producción; en http://127.0.0.1 no se enviaría.
    cookie_segura: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FACTURAS_", extra="ignore")

    @model_validator(mode="after")
    def _produccion_exige_acceso_seguro(self) -> "Settings":
        if self.environment == "produccion" and self.acceso_modo != "seguro":
            raise ValueError("En producción FACTURAS_ACCESO_MODO debe ser 'seguro'.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
