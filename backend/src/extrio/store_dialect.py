"""Dialect shims that let the Extrio store run on SQLite and PostgreSQL.

The store layer is written against a deliberately small SQL subset:

* Every statement is authored with SQLite ``?`` placeholders; the PostgreSQL
  dialect rewrites them to ``%s`` at execution time. SQL templates must
  therefore never contain a literal question mark outside a placeholder.
* JSON payloads are stored as TEXT on SQLite (queried through the json1
  extension) and as ``jsonb`` on PostgreSQL. ``json_param``/``decode_json``
  hide the difference and ``json_extract_text`` supplies the JSON path
  extraction fragment used inside queries.
* Timestamps stay ISO-8601 UTC strings on both dialects so lease expiry,
  schedule, and keyset comparisons behave identically.
* Booleans are INTEGER on SQLite and BOOLEAN on PostgreSQL;
  ``bool_param``/``bool_true`` adapt values and literals.
* ``INSERT OR IGNORE`` becomes ``ON CONFLICT DO NOTHING`` on PostgreSQL, and
  PostgreSQL additionally takes ``FOR UPDATE SKIP LOCKED`` row locks when a
  lease claim runs inside a transaction.
* UPSERT statements use ``ON CONFLICT ... DO UPDATE`` and ``RETURNING``-free
  select-then-update flows only, both of which SQLite and PostgreSQL support.

Connections are wrapped in :class:`DialectConnection` so the store executes
the same SQL against either engine while rows stay indexable by column name
(``sqlite3.Row`` on SQLite, ``dict`` via psycopg's ``dict_row``).
"""

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=30000",
)
POSTGRES_URL_SCHEMES = ("postgresql", "postgres")
MIGRATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class DialectConnection:
    """Thin wrapper normalizing ``execute`` across sqlite3 and psycopg3."""

    def __init__(self, raw: sqlite3.Connection | psycopg.Connection, dialect: "Dialect"):
        self.raw = raw
        self.dialect = dialect

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self.raw.execute(self.dialect.translate_sql(sql), self.dialect.translate_params(params))

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()

    def __enter__(self) -> "DialectConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.close()
        return False


class Dialect(ABC):
    """Per-engine behavior for connecting, transactions, and SQL fragments."""

    name: str

    @abstractmethod
    def connect(self, database_url: str | None, path: Path) -> DialectConnection:
        """Open a new connection with rows indexable by column name."""

    @abstractmethod
    @contextmanager
    def transaction(self, database_url: str | None, path: Path) -> Iterator[DialectConnection]:
        """Yield a connection wrapped in a write transaction."""

    @abstractmethod
    def run_script(self, connection: DialectConnection, script: str) -> None:
        """Execute a multi-statement migration script atomically."""

    @abstractmethod
    def json_param(self, value: Any) -> Any:
        """Encode a JSON payload for a write parameter."""

    @abstractmethod
    def decode_json(self, value: Any) -> Any:
        """Decode a stored JSON payload into Python data."""

    @abstractmethod
    def json_extract_text(self, column: str, key: str) -> str:
        """SQL fragment extracting ``key`` from a JSON column as text."""

    @abstractmethod
    def nocase_equality(self, column: str) -> str:
        """SQL fragment for a case-insensitive ``column = ?`` comparison."""

    @abstractmethod
    def bool_param(self, value: bool) -> Any:
        """Adapt a Python bool for a boolean column."""

    @abstractmethod
    def bool_true(self) -> str:
        """SQL literal representing a true boolean."""

    @abstractmethod
    def insert_or_ignore(self, sql: str) -> str:
        """Rewrite a plain INSERT into an idempotent insert."""

    @abstractmethod
    def row_lock_clause(self) -> str:
        """Suffix locking selected rows against concurrent lease claims."""

    def translate_sql(self, sql: str) -> str:
        return sql

    def translate_params(self, params: tuple[Any, ...]) -> tuple[Any, ...]:
        return tuple(params)


class SQLiteDialect(Dialect):
    """Zero-config local profile: stdlib sqlite3 with WAL and json1."""

    name = "sqlite"

    def connect(self, database_url: str | None, path: Path) -> DialectConnection:
        connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        for pragma in SQLITE_PRAGMAS:
            connection.execute(pragma)
        return DialectConnection(connection, self)

    @contextmanager
    def transaction(self, database_url: str | None, path: Path) -> Iterator[DialectConnection]:
        connection = self.connect(database_url, path)
        try:
            connection.raw.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def run_script(self, connection: DialectConnection, script: str) -> None:
        try:
            connection.raw.executescript(f"BEGIN;\n{script}\nCOMMIT;")
        except Exception:
            connection.raw.rollback()
            raise

    def json_param(self, value: Any) -> Any:
        return json.dumps(value, ensure_ascii=False)

    def decode_json(self, value: Any) -> Any:
        return json.loads(value)

    def json_extract_text(self, column: str, key: str) -> str:
        return f"json_extract({column}, '$.{key}')"

    def nocase_equality(self, column: str) -> str:
        return f"{column}=? COLLATE NOCASE"

    def bool_param(self, value: bool) -> Any:
        return int(value)

    def bool_true(self) -> str:
        return "1"

    def insert_or_ignore(self, sql: str) -> str:
        return sql.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)

    def row_lock_clause(self) -> str:
        return ""


class PostgresDialect(Dialect):
    """Production profile: psycopg3 (sync) against PostgreSQL with jsonb."""

    name = "postgresql"

    def __init__(self, database_url: str):
        self.database_url = database_url

    def connect(self, database_url: str | None, path: Path) -> DialectConnection:
        connection = psycopg.connect(self.database_url, row_factory=dict_row, autocommit=True)
        return DialectConnection(connection, self)

    @contextmanager
    def transaction(self, database_url: str | None, path: Path) -> Iterator[DialectConnection]:
        connection = self.connect(database_url, path)
        try:
            with connection.raw.transaction():
                yield connection
        finally:
            connection.close()

    def run_script(self, connection: DialectConnection, script: str) -> None:
        with connection.raw.transaction():
            connection.raw.execute(script)

    def json_param(self, value: Any) -> Any:
        return Jsonb(value)

    def decode_json(self, value: Any) -> Any:
        return value

    def json_extract_text(self, column: str, key: str) -> str:
        return f"({column}->>'{key}')"

    def nocase_equality(self, column: str) -> str:
        return f"LOWER({column})=LOWER(?)"

    def bool_param(self, value: bool) -> Any:
        return bool(value)

    def bool_true(self) -> str:
        return "TRUE"

    def insert_or_ignore(self, sql: str) -> str:
        return f"{sql} ON CONFLICT DO NOTHING"

    def row_lock_clause(self) -> str:
        return " FOR UPDATE SKIP LOCKED"

    def translate_sql(self, sql: str) -> str:
        return sql.replace("?", "%s")


def resolve_database(database_url: str | None, fallback_path: Path) -> tuple[Dialect, Path]:
    """Resolve EXTRIO_DATABASE_URL into a dialect plus the active SQLite path.

    Unset or empty URLs keep the zero-config SQLite profile at
    ``fallback_path``. ``sqlite:///relative.db`` selects a relative path and
    ``sqlite:////absolute.db`` an absolute one (SQLAlchemy convention). A
    ``postgresql://`` or ``postgres://`` URL selects the PostgreSQL dialect
    and requires a database name in the URL path.
    """

    if not database_url:
        return SQLiteDialect(), fallback_path
    scheme = urlparse(database_url).scheme
    if scheme == "sqlite":
        remainder = database_url.split("://", 1)[1] if "://" in database_url else database_url.removeprefix("sqlite:")
        if remainder.startswith("//"):
            raw_path = remainder[1:]
        elif remainder.startswith("/"):
            raw_path = remainder[1:]
        else:
            raw_path = remainder
        path = Path(unquote(raw_path))
        if not str(path):
            raise ValueError("sqlite database URL must include a file path")
        return SQLiteDialect(), path
    if scheme in POSTGRES_URL_SCHEMES:
        database_name = urlparse(database_url).path.strip("/")
        if not database_name:
            raise ValueError("PostgreSQL database URL must include a database name")
        return PostgresDialect(database_url), fallback_path
    raise ValueError(f"unsupported EXTRIO_DATABASE_URL scheme: {scheme!r}")
