from __future__ import annotations

import argparse
import os
import sys
from uuid import UUID

from app.security.data_plane import DataPlaneError, provision_data_plane_identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vincula de forma irreversible un data plane nuevo con un tenant."
    )
    parser.add_argument("--tenant-id", required=True, type=UUID)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.getenv("FACTURAS_TENANT_MIGRATION_DATABASE_URL")
    if not database_url:
        print("Falta FACTURAS_TENANT_MIGRATION_DATABASE_URL.", file=sys.stderr)
        return 2
    try:
        created = provision_data_plane_identity(database_url, args.tenant_id)
    except DataPlaneError as exc:
        print(f"No fue posible vincular el data plane ({exc.code}).", file=sys.stderr)
        return 1
    print("Data plane vinculado." if created else "El data plane ya tenía esta vinculación.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
