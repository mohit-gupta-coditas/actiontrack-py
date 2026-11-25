from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from actiontrack.clock import FixedClock
from actiontrack.errors import UserInputError
from actiontrack.models import Flag
from actiontrack.services.query import ItemView, list_items, mark_done, resolve_owner_query
from actiontrack.store.repo import ItemRepo, PeopleRepo, SourceRef
from tests.integration.conftest import PRIYA_NAIR, RAHUL, SEEDED, VIKRAM

CLOCK = FixedClock(date(2026, 11, 25), datetime(2026, 11, 25, 9, 30).astimezone())


def listed(conn: sqlite3.Connection, **kw: Any) -> list[str]:
    """Names (keys of `SEEDED`) of the listed items, in order."""
    by_id = {v: k for k, v in SEEDED.items()}
    return [by_id[v.id] for v in list_items(conn, clock=CLOCK, **kw)]


# --- resolve_owner_query ---------------------------------------------------------------------


def test_resolve_owner_query_one(seeded_db: sqlite3.Connection) -> None:
    people = PeopleRepo(seeded_db)
    assert resolve_owner_query("rahul", people).key == RAHUL
    assert resolve_owner_query("Priya Nair", people).key == PRIYA_NAIR


def test_resolve_owner_query_many(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(UserInputError) as e:
        resolve_owner_query("Priya", PeopleRepo(seeded_db))
    assert e.value.message == '"Priya" matches 2 people'
    assert e.value.hint == (
        "Priya Nair <priya.nair@coditas.com>, Priya Shah <priya.shah@coditas.com>"
        " — use full name or email"
    )


def test_resolve_owner_query_none(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(UserInputError, match='no person matches "Zed"'):
        resolve_owner_query(" Zed ", PeopleRepo(seeded_db))


def test_resolve_owner_query_item_owner(seeded_db: sqlite3.Connection) -> None:
    """G11: an owner with no `people` row is found through the items."""
    person = resolve_owner_query("vikram rao", PeopleRepo(seeded_db))
    assert (person.key, person.full_name, person.first_name, person.email) == (
        VIKRAM,
        "Vikram Rao",
        "Vikram",
        VIKRAM,
    )


# --- list_items ------------------------------------------------------------------------------


def test_TC_M8_01_default_view(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db) == [
        "quote", "venue", "projector", "budget", "agenda", "invoice", "contract"
    ]  # fmt: skip


def test_TC_M8_02_status_overdue(seeded_db: sqlite3.Connection) -> None:
    views = list_items(seeded_db, status="overdue", clock=CLOCK)
    assert [v.id for v in views] == [SEEDED["quote"], SEEDED["venue"]]
    assert {v.status for v in views} == {"overdue"}


def test_TC_M8_03_status_done(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, status="done") == ["slides"]


def test_TC_M8_04_owner_first_name(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, owner="Rahul") == ["venue", "agenda"]


def test_TC_M8_05_owner_email(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, owner="priya.nair@coditas.com") == ["contract"]


def test_TC_M8_08_due_before(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, due_before="2026-11-22") == ["quote", "venue"]
    assert listed(seeded_db, due_before="today") == ["quote", "venue"]  # parsed against the clock


def test_TC_M8_09_due_before_invalid(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(UserInputError) as e:
        list_items(seeded_db, due_before="not a date", clock=CLOCK)
    assert e.value.hint is not None and "YYYY-MM-DD" in e.value.hint


def test_TC_M8_10_unassigned(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, unassigned=True) == ["projector", "budget"]


def test_TC_M8_11_flag_ambiguous(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, flag="ambiguous_owner") == ["budget"]


def test_TC_M8_12_flag_orphaned(seeded_db: sqlite3.Connection) -> None:
    views = list_items(seeded_db, flag="orphaned", clock=CLOCK)
    assert [v.id for v in views] == [SEEDED["orphan"]]
    assert "orphaned" in views[0].flags
    assert views[0].sources == ()


def test_TC_M8_13_owner_and_unassigned(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(UserInputError, match="--owner and --unassigned"):
        list_items(seeded_db, owner="Rahul", unassigned=True, clock=CLOCK)


def test_TC_M8_25_owner_not_attendee(seeded_db: sqlite3.Connection) -> None:
    assert listed(seeded_db, owner="vikram") == ["invoice"]


def test_invalid_status_and_flag(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(UserInputError, match='invalid status "late"'):
        list_items(seeded_db, status="late", clock=CLOCK)
    with pytest.raises(UserInputError, match='invalid flag "nope"'):
        list_items(seeded_db, flag="nope", clock=CLOCK)


def test_item_view_mapping(seeded_db: sqlite3.Connection) -> None:
    views = {v.id: v for v in list_items(seeded_db, clock=CLOCK)}
    quote = views[SEEDED["quote"]]
    assert quote == ItemView(
        id=SEEDED["quote"],
        short_id=SEEDED["quote"][:6],
        owner_key="priya.shah@coditas.com",
        owner_display="Priya Shah",
        owner_raw="Priya",
        task="send the revised quote",
        due_date=date(2026, 11, 20),
        status="overdue",
        flags=(),
        sources=(
            SourceRef(Path("notes/2026-11-11-kickoff.md"), 4, date(2026, 11, 11), None),
            SourceRef(Path("notes/2026-11-18-sync.md"), 3, date(2026, 11, 18), None),
        ),
    )
    budget = views[SEEDED["budget"]]
    assert (budget.owner_key, budget.owner_raw, budget.flags) == (
        None,
        "Priya",
        ("ambiguous_owner",),
    )
    assert views[SEEDED["agenda"]].status == "open"


def test_empty_db(conn: sqlite3.Connection) -> None:
    assert list_items(conn, clock=CLOCK) == []


# --- mark_done -------------------------------------------------------------------------------


def test_TC_M8_24_mark_done_records_cli_and_now(seeded_db: sqlite3.Connection) -> None:
    view, changed = mark_done(seeded_db, SEEDED["venue"][:6], clock=CLOCK)
    assert changed
    assert (view.id, view.status, view.short_id) == (SEEDED["venue"], "done", SEEDED["venue"][:6])
    row = ItemRepo(seeded_db).get(SEEDED["venue"], today=CLOCK.today())
    assert row is not None
    assert (row.status, row.done_source, row.done_at) == ("done", "cli", CLOCK.now())


def test_mark_done_already_done(seeded_db: sqlite3.Connection) -> None:
    view, changed = mark_done(seeded_db, SEEDED["slides"], clock=CLOCK)
    assert not changed
    assert view.status == "done"
    row = ItemRepo(seeded_db).get(SEEDED["slides"], today=CLOCK.today())
    assert row is not None and row.done_source == "note"  # untouched


def test_mark_done_orphaned_item(seeded_db: sqlite3.Connection) -> None:
    view, changed = mark_done(seeded_db, SEEDED["orphan"], clock=CLOCK)
    assert changed and Flag.ORPHANED.value in view.flags
