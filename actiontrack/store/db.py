"""SQLite connection, transactions and the migration runner (M6 spec §2)."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

from actiontrack.errors import FatalError

MEMORY = Path(":memory:")
BUSY_TIMEOUT_MS = 5000
_MIGRATION_NAME = re.compile(r"^(\d{4})_\w+\.sql$")


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the DB at `path`, set the pragmas and apply pending migrations."""
    if path != MEMORY:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise FatalError(f"cannot create the database directory for {path}: {e}") from e
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        migrate(conn)
    except sqlite3.DatabaseError as e:
        if conn is not None:
            conn.close()
        raise FatalError(f"cannot open the database {path}: {e}") from e
    except BaseException:
        if conn is not None:
            conn.close()
        raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """`BEGIN IMMEDIATE … COMMIT`, rolled back on any exception (incl. KeyboardInterrupt).

    Re-entrant: inside an open transaction it does nothing, so the outer block owns the commit.
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    """Apply each `migrations/NNNN_*.sql` with NNNN > `user_version`, in its own transaction."""
    migrations = _migrations()
    latest = migrations[-1][0] if migrations else 0
    current = _user_version(conn)
    if current > latest:
        raise FatalError(
            "database was created by a newer actiontrack "
            f"(schema version {current}, this version knows up to {latest})",
            hint="upgrade actiontrack or point --db at another database",
        )
    for version, sql in migrations:
        if version <= current:
            continue
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"
            )
        except sqlite3.DatabaseError:
            if conn.in_transaction:
                conn.rollback()
            # Another process may have applied the same migration while we waited for the lock.
            if _user_version(conn) < version:
                raise
        current = version


def _migrations() -> list[tuple[int, str]]:
    found = []
    for entry in files("actiontrack.store").joinpath("migrations").iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


def _user_version(conn: sqlite3.Connection) -> int:
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return version
