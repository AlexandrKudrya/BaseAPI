"""Database adapters for SQLite and PostgreSQL.

One narrow interface over the two drivers: ``connect(...)`` returns an object
with ``run(sql, params) -> Result`` and ``close()``. ``psycopg`` is only ever
imported lazily, at the moment a PostgreSQL connection is opened without an
injected driver — it is never imported at module import time.
"""

import os
import sqlite3
import threading
from dataclasses import dataclass

from baseapi import dialect
from baseapi.errors import ConfigError


@dataclass
class Result:
    """The outcome of one statement: rows as plain dicts, plus a row count."""

    rows: list
    rowcount: int


def connect(url, *, base_dir=".", init_sql=None, driver=None):
    """Open a database connection for ``url`` and return a ``Database``."""
    if not url:
        raise ConfigError("empty database url")
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        return _SqliteDatabase(base_dir, path, init_sql)
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return _PostgresDatabase(url, init_sql, driver)
    raise ConfigError("unsupported database url scheme: %s" % url)


class _SqliteDatabase:
    def __init__(self, base_dir, path, init_sql):
        if path == ":memory:":
            db_path = ":memory:"
        elif os.path.isabs(path):
            db_path = path
        else:
            db_path = os.path.join(base_dir, path)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        if init_sql:
            self._conn.executescript(init_sql)
            self._conn.commit()

    def run(self, sql, params):
        with self._lock:
            names = dialect.param_names(sql)
            bound = {name: params[name] for name in names if name in params}
            cursor = self._conn.execute(sql, bound)
            result = _collect(cursor)
            self._conn.commit()
            return result

    def close(self):
        self._conn.close()


class _PostgresDatabase:
    def __init__(self, url, init_sql, driver):
        if driver is None:
            import psycopg  # imported lazily, only when a real PG URL is opened

            driver = psycopg
        self._driver = driver
        self._conn = driver.connect(url)
        self._lock = threading.Lock()
        if init_sql:
            cursor = self._conn.cursor()
            cursor.execute(init_sql)
            self._conn.commit()

    def run(self, sql, params):
        with self._lock:
            names = dialect.param_names(sql)
            bound = {name: params[name] for name in names if name in params}
            cursor = self._conn.cursor()
            cursor.execute(dialect.to_pyformat(sql), bound)
            result = _collect(cursor)
            self._conn.commit()
            return result

    def close(self):
        self._conn.close()


def _collect(cursor):
    if cursor.description is not None:
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        rowcount = len(rows)
    else:
        rows = []
        rowcount = cursor.rowcount
    return Result(rows=rows, rowcount=rowcount)
