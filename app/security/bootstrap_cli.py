from __future__ import annotations

import argparse
import os
import sys

from app.security.lifecycle import (
    BootstrapDirectorCommand,
    IdentityLifecycleService,
    LifecycleError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Procedimiento local y de un solo uso para crear el primer director."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "prepare",
        help="Genera una credencial de instalación de 30 minutos y muestra el secreto una sola vez.",
    )
    create = subcommands.add_parser("create-director", help="Consume la credencial de instalación.")
    create.add_argument("--provider-subject", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--primary-authenticator-id", required=True)
    create.add_argument("--backup-authenticator-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.getenv("FACTURAS_CONTROL_DATABASE_URL")
    identity_provider = os.getenv("FACTURAS_OIDC_IDENTITY_PROVIDER")
    if not database_url or not identity_provider:
        print(
            "Faltan FACTURAS_CONTROL_DATABASE_URL y FACTURAS_OIDC_IDENTITY_PROVIDER.",
            file=sys.stderr,
        )
        return 2

    service = IdentityLifecycleService(database_url, identity_provider)
    try:
        if args.command == "prepare":
            token, expires_at = service.prepare_first_director_bootstrap()
            print("Credencial de instalación (se muestra una sola vez):")
            print(token)
            print(f"Expira: {expires_at.isoformat()}")
            print("Guárdela temporalmente en FACTURAS_BOOTSTRAP_TOKEN y no la pase como argumento.")
            return 0

        bootstrap_token = os.getenv("FACTURAS_BOOTSTRAP_TOKEN", "")
        identity_id = service.create_first_director(
            bootstrap_token,
            BootstrapDirectorCommand(
                provider_subject=args.provider_subject,
                email=args.email,
                display_name=args.display_name,
                primary_authenticator_id=args.primary_authenticator_id,
                backup_authenticator_id=args.backup_authenticator_id,
            ),
        )
        os.environ.pop("FACTURAS_BOOTSTRAP_TOKEN", None)
        print(f"Primer director creado: {identity_id}")
        print("Elimine FACTURAS_BOOTSTRAP_TOKEN del entorno que inició este proceso.")
        return 0
    except LifecycleError as exc:
        print(f"No fue posible completar la instalación ({exc.code}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
