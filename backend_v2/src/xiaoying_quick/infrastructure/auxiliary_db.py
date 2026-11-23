"""Connection handling for workbook and dashboard stores."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import make_url


class NamedRow(dict):
    """A mapping with the positional lookup also supported by sqlite3.Row."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _named_row(cursor):
    from psycopg.rows import dict_row

    build = dict_row(cursor)
    return lambda values: NamedRow(build(values))


class PostgresStatements:
    """The stores use positional question marks in their static SQL statements."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        return self.connection.execute(sql.replace("?", "%s"), parameters)

    def executemany(self, sql, records):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), records)

    def executescript(self, ddl):
        self.connection.execute(ddl)


class AuxiliaryDatabase:
    def __init__(self, path: Path, database_url: str | None, *, lock_id: int):
        self.path = path
        self.lock_id = lock_id
        url = make_url(database_url) if database_url else None
        self.postgres = bool(url and url.get_backend_name() == "postgresql")
        self.dsn = (
            url.set(drivername="postgresql").render_as_string(hide_password=False)
            if self.postgres else None
        )
        if not self.postgres:
            path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self, *, write=False, named=False):
        if self.postgres:
            import psycopg
            from psycopg.rows import tuple_row

            with psycopg.connect(self.dsn, row_factory=_named_row if named else tuple_row) as conn:
                conn.execute("SET LOCAL search_path TO workspace")
                if write:
                    # Preserve atomic quota, queue and board-version checks across connections.
                    conn.execute("SELECT pg_advisory_xact_lock(724081, %s)", (self.lock_id,))
                yield PostgresStatements(conn)
            return

        conn = sqlite3.connect(str(self.path), timeout=15)
        try:
            if named:
                conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                if write:
                    conn.execute("BEGIN IMMEDIATE")
                yield conn
        finally:
            conn.close()
