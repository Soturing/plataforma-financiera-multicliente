import argparse
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.jobs import _process_batch, _process_invoice


def advisory_key(identifier: UUID) -> int:
    return int.from_bytes(identifier.bytes[:8], "big", signed=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--batch", type=UUID)
    target.add_argument("--invoice", type=UUID)
    args = parser.parse_args()
    identifier = args.batch or args.invoice
    settings = get_settings()

    with psycopg.connect(settings.database_url, row_factory=dict_row) as lock_conn:
        acquired = lock_conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (advisory_key(identifier),),
        ).fetchone()["acquired"]
        if not acquired:
            return
        if args.batch:
            _process_batch(args.batch)
        else:
            row = lock_conn.execute(
                "SELECT archivo_url FROM core.facturas WHERE id = %s",
                (args.invoice,),
            ).fetchone()
            if row:
                _process_invoice(args.invoice, row["archivo_url"])


if __name__ == "__main__":
    main()
