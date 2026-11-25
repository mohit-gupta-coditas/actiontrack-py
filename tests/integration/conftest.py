"""Builders and fixtures shared by the integration tests: stored notes, sources and item groups."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pytest

from actiontrack.dedup import DedupResult, make_item_id, normalize_task
from actiontrack.models import Attendee, Flag, ItemGroup, NoteMeta, OwnerResolution, ParsedItem
from actiontrack.store.db import MEMORY, connect
from actiontrack.store.repo import ItemRepo, NoteRepo, PeopleRepo, SourceRepo
from tests.unit.conftest import owner, src

__all__ = ["SEEDED", "add_note", "group", "owner", "seed", "src", "store_sources"]

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


# --- seeded_db (M8) --------------------------------------------------------------------------

PRIYA_SHAH = "priya.shah@coditas.com"
PRIYA_NAIR = "priya.nair@coditas.com"
RAHUL = "rahul.mehta@coditas.com"
VIKRAM = "vikram.rao@coditas.com"  # an owner who is not an attendee: no `people` row (G11)
_ORPHAN_NOTE = "notes/2026-11-02-old.md"


def _person(key: str, name: str, flags: frozenset[Flag] = frozenset()) -> OwnerResolution:
    return OwnerResolution(key, name, name.split()[0], flags, ())


def _seed_groups() -> dict[str, ItemGroup]:
    """The seeded items by name. With `FixedClock(2026-11-25)`: two overdue, one orphaned."""
    note = "notes/2026-11-18-sync.md"
    ambiguous = OwnerResolution(
        None, None, "Priya", frozenset({Flag.AMBIGUOUS_OWNER}), (PRIYA_NAIR, PRIYA_SHAH)
    )
    vikram = _person(VIKRAM, "Vikram Rao", frozenset({Flag.OWNER_NOT_ATTENDEE}))
    return {
        "quote": group(
            src(_person(PRIYA_SHAH, "Priya Shah"), "send the revised quote", "2026-11-18",
                line=3, due="2026-11-20", path=note),
            src(_person(PRIYA_SHAH, "Priya Shah"), "Send the revised quote", "2026-11-11",
                line=4, due="2026-11-20", path="notes/2026-11-11-kickoff.md"),
        ),
        "venue": group(src(_person(RAHUL, "Rahul Mehta"), "book the venue", "2026-11-18",
                           line=4, due="2026-11-21", path=note)),
        "agenda": group(src(_person(RAHUL, "Rahul Mehta"), "draft the agenda", "2026-11-18",
                            line=5, due="2026-12-01", path=note)),
        "contract": group(src(_person(PRIYA_NAIR, "Priya Nair"), "review the contract",
                              "2026-11-18", line=6, path=note), flags=frozenset({Flag.NO_DUE})),
        "slides": group(src(_person(PRIYA_SHAH, "Priya Shah"), "share the slides", "2026-11-18",
                            line=7, due="2026-11-10", checked=True, path=note), status="done"),
        "projector": group(src(None, "fix the projector", "2026-11-18", line=8,
                               due="2026-11-28", path=note), flags=frozenset({Flag.UNASSIGNED})),
        "budget": group(src(ambiguous, "update the budget", "2026-11-18", line=9,
                            due="2026-11-30", path=note), flags=ambiguous.flags),
        "invoice": group(src(vikram, "send the invoice", "2026-11-18", line=10,
                             due="2026-12-05", path=note), flags=vikram.flags),
        "orphan": group(src(_person(RAHUL, "Rahul Mehta"), "renew the domain", "2026-11-02",
                            line=3, due="2026-11-15", path=_ORPHAN_NOTE)),
    }  # fmt: skip


SEEDED: dict[str, str] = {name: g.id for name, g in _seed_groups().items()}


def seed(conn: sqlite3.Connection, *extra: ItemGroup) -> None:
    """Store the seeded people and items, plus `extra` groups, through the M6 repos.

    The `orphan` item loses its only note (deleted, as ingest does for a removed file), so it
    ends up flagged `orphaned`.
    """
    PeopleRepo(conn).upsert_many(
        Attendee(name, name.split()[0], name.split()[1], None, key, key)
        for name, key in (
            ("Priya Shah", PRIYA_SHAH), ("Priya Nair", PRIYA_NAIR), ("Rahul Mehta", RAHUL)
        )
    )  # fmt: skip
    groups = [*_seed_groups().values(), *extra]
    store_sources(conn, *(s for g in groups for s in g.sources))
    items = ItemRepo(conn)
    items.apply_groups(DedupResult(groups=tuple(groups), decisions=(), orphaned_ids=()))
    NoteRepo(conn).delete(Path(_ORPHAN_NOTE))
    kept = tuple(g for g in groups if g.id != SEEDED["orphan"])
    items.apply_groups(DedupResult(kept, decisions=(), orphaned_ids=(SEEDED["orphan"],)))


@pytest.fixture
def seeded_db(conn: sqlite3.Connection) -> sqlite3.Connection:
    """The M8 test DB (M8 tests.md): three people and nine items, built through the repos."""
    seed(conn)
    return conn
