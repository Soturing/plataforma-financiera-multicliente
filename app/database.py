from collections.abc import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.config import get_settings


def get_connection() -> Iterator[Connection]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        yield connection
