"""Prepara un data plane desechable para correr la suite (integración continua o local).

Usa los mismos pasos que el alta de un cliente: cuentas tenant_owner y tenant_runtime,
todas las migraciones como propietaria e identidad del tenant. Escribe en
`$GITHUB_ENV` (o imprime) las variables que espera pytest.

    python scripts/preparar_base_pruebas.py --puerto 5432 --admin-password postgres --clave PRUEBAS-CI
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.plataforma import tenants  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puerto", default="5432")
    parser.add_argument("--admin-password", required=True, help="Contraseña de dp_admin (superusuario del contenedor)")
    parser.add_argument("--clave", default="PRUEBAS-CI")
    args = parser.parse_args()
    env = {
        "DP_DB_PORT": args.puerto,
        "DP_ADMIN_PASSWORD": args.admin_password,
        "TENANT_OWNER_PASSWORD": secrets.token_urlsafe(24),
        "TENANT_RUNTIME_PASSWORD": secrets.token_urlsafe(24),
    }
    for _ in range(30):
        try:
            with tenants.conectar(tenants.url_base(env, "dp_admin", "DP_ADMIN_PASSWORD")) as c:
                c.execute("SELECT 1")
            break
        except Exception:
            time.sleep(2)
    tenants.crear_roles(env)
    print(f"Migraciones aplicadas: {len(tenants.aplicar_migraciones(env))}")
    tenants.fijar_identidad(env, args.clave)
    variables = {
        "TENANT_OWNER_URL": tenants.url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD"),
        "FACTURAS_DATABASE_URL": tenants.url_base(env, "tenant_runtime", "TENANT_RUNTIME_PASSWORD"),
        "FACTURAS_TENANT_CLAVE": args.clave,
    }
    destino = os.environ.get("GITHUB_ENV")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.writelines(f"{k}={v}\n" for k, v in variables.items())
    else:
        for k, v in variables.items():
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
