"""Builders and fixtures shared by the integration tests: stored notes, sources and item groups."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pytest

from actiontrack.dedup import make_item_id, normalize_task
from actiontrack.models import Flag, ItemGroup, NoteMeta, ParsedItem
from actiontrack.store.db import MEMORY, connect
from actiontrack.store.repo import NoteRepo, SourceRepo
from tests.unit.conftest import owner, src

__all__ = ["add_note", "group", "owner", "src", "store_sources"]

NOW = datetime(2026, 11, 25, 10, 0).astimezone()


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh, migrated in-memory DB."""
    c = connect(MEMORY)
    yield c
    c.close()


def add_note(conn: sqlite3.Connection, path: str | Path, meeting: str = "2026-11-18") -> Path:
    p = Path(path)
    meta = NoteMeta(p, f"sha-{p.as_posix()}", date.fromisoformat(meeting), None, (), ())
    NoteRepo(conn).upsert_ok(meta, now=NOW)
    return p


def store_sources(conn: sqlite3.Connection, *items: ParsedItem) -> None:
    """Store `items` grouped by note, adding each note first."""
    by_note: dict[Path, list[ParsedItem]] = {}
    for i in items:
        by_note.setdefault(i.note_path, []).append(i)
    for path, sources in by_note.items():
        add_note(conn, path, sources[0].meeting_date.isoformat())
        SourceRepo(conn).replace_for_note(path, sources)


def group(
    *sources: ParsedItem,
    item_id: str | None = None,
    due: str | None = None,
    status: Literal["open", "done"] = "open",
    flags: frozenset[Flag] = frozenset(),
    owner_display: str | None = None,
) -> ItemGroup:
    """An `ItemGroup` over `sources` (at least one), with the fields a test cares about set."""
    first = sources[0]
    norm = normalize_task(first.task)
    return ItemGroup(
        id=item_id or make_item_id(first.owner.owner_key, norm),
        owner_key=first.owner.owner_key,
        owner_display=owner_display or first.owner.owner_display,
        owner_raw=first.owner.owner_raw,
        task=first.task,
        task_norm=norm,
        due_date=date.fromisoformat(due) if due else first.due.due_date,
        due_raw=first.due.due_raw,
        status=status,
        done_source="note" if status == "done" else None,
        done_at=None,
        flags=flags,
        first_seen=min(s.meeting_date for s in sources),
        last_seen=max(s.meeting_date for s in sources),
        sources=sources,
    )
