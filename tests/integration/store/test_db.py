from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from actiontrack.errors import FatalError
from actiontrack.store import db
from actiontrack.store.db import MEMORY, connect, migrate, transaction
from actiontrack.store.repo import ItemFilter, ItemRepo

TABLES = {"notes", "people", "items", "item_sources", "drafts"}


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r[0] for r in rows}


def user_version(conn: sqlite3.Connection) -> int:
    v: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return v


# --- connect & migrations --------------------------------------------------------------------


def test_TC_M6_01_connect_creates_dir_and_schema(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "t.db"
    conn = connect(path)
    try:
        assert path.parent.is_dir()
        assert tables(conn) >= TABLES
        assert user_version(conn) == 1
    finally:
        conn.close()


def test_TC_M6_02_reconnect_does_not_reapply_migrations(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    connect(path).close()
    conn = connect(path)  # CREATE TABLE would fail if 0001 ran again
    try:
        assert user_version(conn) == 1
        assert tables(conn) >= TABLES
    finally:
        conn.close()


def test_TC_M6_03_newer_schema_is_fatal(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 99")
    raw.close()
    with pytest.raises(FatalError, match="newer actiontrack"):
        connect(path)


def test_TC_M6_04_pragmas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_TC_M6_05_writer_waits_for_lock(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    a = connect(path)
    result: dict[str, object] = {}

    def writer() -> None:
        b = connect(path)
        start = time.monotonic()
        try:
            with transaction(b):
                b.execute("INSERT INTO people (key, full_name, first_name) VALUES ('k', 'K', 'K')")
            result["waited"] = time.monotonic() - start
        except Exception as e:  # pragma: no cover - reported by the assertion below
            result["error"] = e
        finally:
            b.close()

    try:
        a.execute("BEGIN IMMEDIATE")
        t = threading.Thread(target=writer)
        t.start()
        time.sleep(0.4)
        a.commit()
        t.join(timeout=10)
        assert "error" not in result, result
        assert float(result["waited"]) >= 0.2  # type: ignore[arg-type]
        assert a.execute("SELECT count(*) FROM people").fetchone()[0] == 1
    finally:
        a.close()


def test_TC_M6_06_indexes_used_by_main_queries(conn: sqlite3.Connection) -> None:
    def plan(f: ItemFilter) -> str:
        sql, params = ItemRepo(conn)._select_sql(f, today=date(2026, 11, 25))
        return " ".join(r["detail"] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, params))

    assert "ix_items_owner" in plan(ItemFilter(owner_keys=("priya.shah@coditas.com",)))
    assert "ix_items_status_due" in plan(ItemFilter(status="overdue"))
    assert "ix_items_status_due" in plan(ItemFilter(status="open"))


def test_TC_M6_07_transaction_rolls_back_on_keyboard_interrupt(conn: sqlite3.Connection) -> None:
    with pytest.raises(KeyboardInterrupt), transaction(conn):
        conn.execute("INSERT INTO people (key, full_name, first_name) VALUES ('k', 'K', 'K')")
        raise KeyboardInterrupt
    assert not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0


@pytest.mark.skipif(sys.platform == "win32", reason="read-only directories can't be simulated")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores modes")
def test_TC_M6_21_read_only_dir_is_fatal(tmp_path: Path) -> None:  # pragma: no cover - POSIX
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(FatalError, match=r"t\.db"):
            connect(ro / "t.db")
    finally:
        ro.chmod(0o700)


# --- edge cases ------------------------------------------------------------------------------


def test_path_that_is_a_directory_is_fatal(tmp_path: Path) -> None:
    target = tmp_path / "dir.db"
    target.mkdir()
    with pytest.raises(FatalError, match=r"dir\.db"):
        connect(target)


def test_parent_that_is_a_file_is_fatal(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x")
    with pytest.raises(FatalError, match="file"):
        connect(tmp_path / "file" / "t.db")


def test_not_a_database_is_fatal(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    path.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(FatalError, match=r"t\.db"):
        connect(path)


def test_memory_db_supported() -> None:
    conn = connect(MEMORY)
    try:
        assert tables(conn) >= TABLES
    finally:
        conn.close()


def test_nested_transaction_is_owned_by_outer(conn: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), transaction(conn):
        with transaction(conn):
            conn.execute("INSERT INTO people (key, full_name, first_name) VALUES ('k', 'K', 'K')")
        assert conn.in_transaction  # the inner block did not commit
        raise RuntimeError
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 0


def test_transaction_commits(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("INSERT INTO people (key, full_name, first_name) VALUES ('k', 'K', 'K')")
    assert not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM people").fetchone()[0] == 1


def test_failing_migration_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db, "_migrations", lambda: [(1, "CREATE TABLE t (x);"), (2, "CREATE TABLE u (x); nope;")]
    )
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn)
        assert not conn.in_transaction
        assert user_version(conn) == 1
        assert tables(conn) == {"t"}
    finally:
        conn.close()


def test_migration_applied_concurrently_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    calls = iter([0, 1])  # we read 0, then another process applies v1 before our script runs
    monkeypatch.setattr(db, "_user_version", lambda c: next(calls))
    monkeypatch.setattr(db, "_migrations", lambda: [(1, "this is not sql;")])
    try:
        migrate(conn)
    finally:
        conn.close()
