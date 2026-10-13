"""Persistent integrated-source identity; candidate collection never writes here."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import _require_video_id

_COMPONENT = "source_catalog"
_SCHEMA_VERSION = 1
_METADATA_COLUMNS = (("component", "TEXT", 1, 1), ("version", "INTEGER", 1, 0))
_SOURCE_COLUMNS = (("video_id", "TEXT", 1, 1), ("registered_at_utc", "TEXT", 1, 0))


class SourceCatalogError(RuntimeError):
    """The persistent integrated-source catalog could not be used safely."""


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _require_columns(
    connection: sqlite3.Connection, table: str, expected: tuple[tuple, ...]
) -> None:
    columns = tuple(
        (row[1], row[2].upper(), row[3], row[5])
        for row in connection.execute("SELECT * FROM pragma_table_info(?)", (table,))
    )
    if columns != expected:
        raise SourceCatalogError("Source catalog schema is inconsistent")


def _require_binary_primary_key(
    connection: sqlite3.Connection, table: str, column: str
) -> None:
    primary_indexes = connection.execute(
        "SELECT name FROM pragma_index_list(?) WHERE origin = 'pk'",
        (table,),
    ).fetchall()
    if len(primary_indexes) != 1:
        raise SourceCatalogError("Source catalog identity constraint is inconsistent")
    primary_columns = connection.execute(
        'SELECT name, coll FROM pragma_index_xinfo(?) WHERE "key" = 1',
        (primary_indexes[0][0],),
    ).fetchall()
    if primary_columns != [(column, "BINARY")]:
        raise SourceCatalogError("Source catalog identities must use case-sensitive comparison")


def _require_schema(connection: sqlite3.Connection) -> None:
    _require_columns(connection, "schema_metadata", _METADATA_COLUMNS)
    _require_binary_primary_key(connection, "schema_metadata", "component")
    version = connection.execute(
        "SELECT version FROM schema_metadata WHERE component = ?", (_COMPONENT,)
    ).fetchone()
    if version is None or type(version[0]) is not int or version[0] != _SCHEMA_VERSION:
        raise SourceCatalogError("Source catalog schema version is missing or unsupported")
    _require_columns(connection, "integrated_sources", _SOURCE_COLUMNS)
    _require_binary_primary_key(connection, "integrated_sources", "video_id")


class SQLiteSourceCatalog:
    """Explicit setup, read-only lookup, and post-Bronze registration.

    Construction does not create files or migrate a database. The caller of
    register_integrated must have already persisted the selected source to Bronze.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0):
        if str(path) == ":memory:":
            raise ValueError("A persistent source catalog requires a filesystem path")
        if (type(timeout_seconds) not in (int, float)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("Source catalog timeout must be finite and positive")
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds

    @contextmanager
    def _connection(self, mode: str) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path.as_uri() + f"?mode={mode}",
            uri=True,
            timeout=self.timeout_seconds,
            isolation_level=None,
        )
        try:
            yield connection
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()

    def _initialize(self) -> None:
        if sqlite3.sqlite_version_info < (3, 24, 0):
            raise SourceCatalogError("Source catalog requires SQLite 3.24 or newer")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection("rwc") as connection:
                connection.execute("BEGIN IMMEDIATE")
                if not _table_exists(connection, "schema_metadata"):
                    if _table_exists(connection, "integrated_sources"):
                        raise SourceCatalogError("Cannot adopt an unversioned source catalog")
                    connection.execute(
                        "CREATE TABLE schema_metadata ("
                        "component TEXT NOT NULL PRIMARY KEY COLLATE BINARY, "
                        "version INTEGER NOT NULL CHECK (version > 0))"
                    )
                _require_columns(connection, "schema_metadata", _METADATA_COLUMNS)
                _require_binary_primary_key(connection, "schema_metadata", "component")
                version = connection.execute(
                    "SELECT version FROM schema_metadata WHERE component = ?", (_COMPONENT,)
                ).fetchone()
                if version is None:
                    if _table_exists(connection, "integrated_sources"):
                        raise SourceCatalogError("Cannot adopt an unversioned source catalog")
                    connection.execute(
                        "CREATE TABLE integrated_sources ("
                        "video_id TEXT NOT NULL PRIMARY KEY COLLATE BINARY "
                        "CHECK (length(video_id) > 0), "
                        "registered_at_utc TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO schema_metadata (component, version) VALUES (?, ?)",
                        (_COMPONENT, _SCHEMA_VERSION),
                    )
                _require_schema(connection)
                connection.commit()
        except (sqlite3.Error, OSError) as error:
            raise SourceCatalogError("Cannot initialize the source catalog") from error

    def is_integrated(self, video_id: str) -> bool:
        """Look up the global video identity without creating or modifying state."""
        _require_video_id(video_id)
        try:
            with self._connection("ro") as connection:
                connection.execute("BEGIN")
                _require_schema(connection)
                found = connection.execute(
                    "SELECT 1 FROM integrated_sources WHERE video_id = ?", (video_id,)
                ).fetchone() is not None
                connection.commit()
                return found
        except sqlite3.Error as error:
            raise SourceCatalogError("Cannot read the integrated-source catalog") from error

    def load_integrated_ids(self) -> frozenset[str]:
        """Materialize one consistent snapshot and close SQL before discovery."""
        try:
            with self._connection("ro") as connection:
                connection.execute("BEGIN")
                _require_schema(connection)
                identities = frozenset(
                    row[0] for row in connection.execute("SELECT video_id FROM integrated_sources")
                )
                for video_id in identities:
                    _require_video_id(video_id)
                connection.commit()
                return identities
        except (sqlite3.Error, ValueError) as error:
            raise SourceCatalogError("Cannot read a valid integrated-source snapshot") from error

    def register_integrated(self, video_id: str) -> bool:
        """Register only AFTER successful Bronze persistence; never during discovery.

        Return True for a new identity, False if already registered. The caller owns
        the Bronze-success precondition; this capability does not write Bronze.
        """
        _require_video_id(video_id)
        try:
            with self._connection("rw") as connection:
                connection.execute("BEGIN IMMEDIATE")
                _require_schema(connection)
                inserted = connection.execute(
                    "INSERT INTO integrated_sources (video_id, registered_at_utc) "
                    "VALUES (?, ?) ON CONFLICT(video_id) DO NOTHING",
                    (video_id, datetime.now(timezone.utc).isoformat()),
                ).rowcount == 1
                connection.commit()
                return inserted
        except sqlite3.Error as error:
            raise SourceCatalogError("Cannot register the integrated source") from error


def initialize_source_catalog(
    path: str | Path, *, timeout_seconds: float = 5.0
) -> SQLiteSourceCatalog:
    """Explicitly create/migrate the catalog; collection never calls this function."""
    catalog = SQLiteSourceCatalog(path, timeout_seconds=timeout_seconds)
    catalog._initialize()
    return catalog
