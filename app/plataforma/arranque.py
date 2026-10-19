"""Punto de entrada del contenedor de un cliente (fase 7, D-025).

Uso (lo invoca la imagen):  python -m app.plataforma.arranque api|workers

1. Con la identidad AppRole de la app del cliente (SECRETOS_APP_ROLE_ID/SECRET_ID)
   obtiene de OpenBao la conexión a su base y los secretos compartidos.
2. Ajusta la dirección de la base a la red interna del stack (ARRANQUE_DB_HOST).
3. Borra del entorno la credencial de OpenBao y reemplaza este proceso por uvicorn o
   por el supervisor de workers: ni la app ni sus hijos ven la credencial.

Si OpenBao está sellado, falla con un mensaje claro y el contenedor se reinicia hasta
que el director lo abra (política `restart: unless-stopped`).
"""
from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlsplit, urlunsplit

from app.plataforma import secretos

_CREDENCIALES = ("SECRETOS_APP_ROLE_ID", "SECRETOS_APP_SECRET_ID")


def url_interna(url: str, host: str | None, puerto: str = "5432") -> str:
    """Cambia host:puerto de la URL de la base por el servicio interno del stack."""
    if not host:
        return url
    partes = urlsplit(url)
    credenciales = partes.netloc.rsplit("@", 1)[0]
    return urlunsplit(partes._replace(netloc=f"{credenciales}@{host}:{puerto}"))


def preparar_entorno(entorno: dict[str, str]) -> dict[str, str]:
    clave = entorno["FACTURAS_TENANT_CLAVE"]
    obtenidos = secretos.secretos_arranque(clave, entorno["SECRETOS_APP_ROLE_ID"], entorno["SECRETOS_APP_SECRET_ID"])
    nuevo = {k: v for k, v in entorno.items() if k not in _CREDENCIALES}
    nuevo.update(obtenidos)
    nuevo["FACTURAS_DATABASE_URL"] = url_interna(
        obtenidos["FACTURAS_DATABASE_URL"], entorno.get("ARRANQUE_DB_HOST"), entorno.get("ARRANQUE_DB_PORT", "5432")
    )
    if nuevo.get("FACTURAS_CONTROL_DATABASE_URL"):
        nuevo["FACTURAS_CONTROL_DATABASE_URL"] = url_interna(
            nuevo["FACTURAS_CONTROL_DATABASE_URL"], entorno.get("ARRANQUE_CONTROL_DB_HOST"),
            entorno.get("ARRANQUE_CONTROL_DB_PORT", "5432"),
        )
    return nuevo


def main(argv: list[str] | None = None) -> int:
    modo = (argv or sys.argv[1:] or ["api"])[0]
    for intento in range(1, 31):
        try:
            entorno = preparar_entorno(dict(os.environ))
            break
        except secretos.SecretosError as error:
            print(f"Esperando a OpenBao ({intento}/30): {error}", file=sys.stderr, flush=True)
            time.sleep(10)
    else:
        print("OpenBao no respondió o sigue sellado: abra con `python -m app.plataforma.secretos abrir`.", file=sys.stderr)
        return 3
    if modo == "api":
        comando = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
                   "--proxy-headers", "--forwarded-allow-ips", entorno.get("ARRANQUE_PROXY_IPS", "*")]
    elif modo == "workers":
        comando = [sys.executable, "-m", "app.worker_cli"]
    else:
        print(f"Modo desconocido: {modo} (api | workers)", file=sys.stderr)
        return 2
    os.execvpe(comando[0], comando, entorno)
    return 0


if __name__ == "__main__":
    sys.exit(main())
