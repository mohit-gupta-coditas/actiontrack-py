from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from actiontrack.clock import FixedClock
from actiontrack.dedup import DedupResult, normalize_task
from actiontrack.models import (
    Attendee,
    Flag,
    ItemGroup,
    OwnerResolution,
    SkipReason,
    SkipRecord,
)
from actiontrack.store.repo import (
    DraftRepo,
    ItemFilter,
    ItemRepo,
    NoteRepo,
    PeopleRepo,
    SourceRef,
    SourceRepo,
)
from tests.integration.conftest import NOW, add_note, group, src, store_sources

PRIYA = "priya.shah@coditas.com"
RAHUL = "rahul.mehta@coditas.com"
CLOCK = FixedClock(date(2026, 11, 25))
TODAY = CLOCK.today()


def apply(conn: sqlite3.Connection, *groups: ItemGroup, orphaned: tuple[str, ...] = ()) -> None:
    ItemRepo(conn).apply_groups(DedupResult(groups=groups, decisions=(), orphaned_ids=orphaned))


def ids(rows: list) -> list[str]:  # type: ignore[type-arg]
    return [r.id for r in rows]


def stored(conn: sqlite3.Connection, *groups: ItemGroup) -> None:
    store_sources(conn, *(s for g in groups for s in g.sources))
    apply(conn, *groups)


def attendee(full: str, email: str | None, *, key: str | None = None) -> Attendee:
    first, _, last = full.partition(" ")
    derived = f"{first}.{last}@coditas.com".lower() if last else None
    return Attendee(
        full, first, last or None, email, key or email or derived or f"name:{first}", derived
    )


# --- notes & sources -------------------------------------------------------------------------


def test_TC_M6_08_sources_round_trip(conn: sqlite3.Connection) -> None:
    ambiguous = OwnerResolution(
        None, None, "Priya", frozenset({Flag.AMBIGUOUS_OWNER}), (RAHUL, PRIYA)
    )
    items = [
        src(PRIYA, "Send quote", "2026-11-18", line=3, due="2026-11-20", path="n.md"),
        src(ambiguous, "Book room", "2026-11-18", line=5, due_raw="ASAP", path="n.md"),
        src(None, "Ship v2", "2026-11-18", line=9, checked=True, path="n.md"),
    ]
    items = [dataclasses.replace(i, note_title="Weekly") for i in items]
    store_sources(conn, *items)
    repo = SourceRepo(conn)
    assert repo.all() == items
    assert repo.count() == 3
    assert repo.all()[1].owner.candidates == (RAHUL, PRIYA)  # order kept, not sorted


def test_due_span_is_not_stored(conn: sqlite3.Connection) -> None:
    i = src(PRIYA, "Send quote", "2026-11-18", due="2026-11-20")
    i = dataclasses.replace(i, due=dataclasses.replace(i.due, span=(5, 10)))
    store_sources(conn, i)
    assert SourceRepo(conn).all()[0].due.span is None


def test_sources_ordered_by_meeting_path_line(conn: sqlite3.Connection) -> None:
    store_sources(
        conn,
        src(PRIYA, "c", "2026-11-18", line=2, path="b.md"),
        src(PRIYA, "a", "2026-11-04", line=7, path="z.md"),
        src(PRIYA, "b", "2026-11-18", line=1, path="b.md"),
    )
    assert [s.task for s in SourceRepo(conn).all()] == ["a", "b", "c"]


def test_replace_for_note_replaces(conn: sqlite3.Connection) -> None:
    store_sources(
        conn, src(PRIYA, "old", "2026-11-18", line=1), src(PRIYA, "x", "2026-11-18", line=2)
    )
    SourceRepo(conn).replace_for_note(Path("a.md"), [src(PRIYA, "new", "2026-11-18", line=1)])
    assert [s.task for s in SourceRepo(conn).all()] == ["new"]


def test_replace_for_note_rejects_other_notes_sources(conn: sqlite3.Connection) -> None:
    add_note(conn, "a.md")
    with pytest.raises(ValueError, match=r"b\.md"):
        SourceRepo(conn).replace_for_note(
            Path("a.md"), [src(PRIYA, "x", "2026-11-18", path="b.md")]
        )


def test_TC_M6_09_upsert_skipped_removes_sources(conn: sqlite3.Connection) -> None:
    store_sources(conn, src(PRIYA, "Send quote", "2026-11-18", path="n.md"))
    notes = NoteRepo(conn)
    rec = SkipRecord(Path("n.md"), SkipReason.MISSING_DATE, "no date found", None)
    notes.upsert_skipped(rec, sha256="abc", now=NOW)
    row = notes.get(Path("n.md"))
    assert row is not None
    assert (row.status, row.skip_reason, row.skip_detail, row.sha256) == (
        "skipped", "missing_date", "no date found", "abc"
    )  # fmt: skip
    assert row.meeting_date is None
    assert SourceRepo(conn).count() == 0


def test_note_get_and_upsert_ok(conn: sqlite3.Connection) -> None:
    notes = NoteRepo(conn)
    assert notes.get(Path("n.md")) is None
    notes.upsert_skipped(
        SkipRecord(Path("n.md"), SkipReason.READ_ERROR, "denied"), sha256=None, now=NOW
    )
    add_note(conn, "n.md", "2026-11-18")
    row = notes.get(Path("n.md"))
    assert row is not None
    assert (row.status, row.sha256, row.meeting_date) == ("ok", "sha-n.md", date(2026, 11, 18))
    assert (row.skip_reason, row.skip_detail) == (None, None)
    assert row.ingested_at == NOW


def test_paths_under_and_delete_cascades(conn: sqlite3.Connection) -> None:
    for p in ("notes/a.md", "notes/sub/b.md", "notes2/c.md", "other.md"):
        add_note(conn, p)
    SourceRepo(conn).replace_for_note(
        Path("notes/a.md"), [src(PRIYA, "x", "2026-11-18", path="notes/a.md")]
    )
    notes = NoteRepo(conn)
    assert notes.paths_under(Path("notes")) == [Path("notes/a.md"), Path("notes/sub/b.md")]
    notes.delete(Path("notes/a.md"))
    assert notes.get(Path("notes/a.md")) is None
    assert SourceRepo(conn).count() == 0


# --- people ----------------------------------------------------------------------------------


def test_TC_M6_10_explicit_email_not_overwritten(conn: sqlite3.Connection) -> None:
    people = PeopleRepo(conn)
    people.upsert_many([attendee("Priya", "priya@coditas.com", key="name:priya")])
    people.upsert_many([attendee("Priya", None, key="name:priya")])
    person = people.get("name:priya")
    assert person is not None
    assert person.email == "priya@coditas.com"


def test_people_store_derived_email_and_first_name_only(conn: sqlite3.Connection) -> None:
    people = PeopleRepo(conn)
    people.upsert_many([attendee("Priya Shah", None), attendee("Vikram", None)])
    p = people.get(PRIYA)
    assert p is not None and p.email == PRIYA
    v = people.get("name:Vikram")
    assert v is not None and v.email is None
    assert people.get("nobody") is None


def test_TC_M6_11_find(conn: sqlite3.Connection) -> None:
    people = PeopleRepo(conn)
    people.upsert_many(
        [attendee("Priya Shah", None), attendee("Priya Nair", None), attendee("Rahul Mehta", None)]
    )
    assert len(people.find("priya")) == 2
    assert [p.key for p in people.find("  PRIYA   nair ")] == ["priya.nair@coditas.com"]
    assert [p.key for p in people.find("rahul.mehta@coditas.com")] == [RAHUL]
    assert people.find("") == []
    assert people.find("nobody") == []


# --- items: query ----------------------------------------------------------------------------


@pytest.fixture
def four(conn: sqlite3.Connection) -> dict[str, str]:
    """Open due yesterday, open due tomorrow, done due yesterday, open with no due."""
    yesterday, tomorrow = TODAY - timedelta(days=1), TODAY + timedelta(days=1)
    gs = {
        "overdue": group(src(PRIYA, "overdue", "2026-11-18", line=1, due=yesterday)),
        "tomorrow": group(src(PRIYA, "tomorrow", "2026-11-18", line=2, due=tomorrow)),
        "done": group(src(PRIYA, "done", "2026-11-18", line=3, due=yesterday), status="done"),
        "nodue": group(src(PRIYA, "nodue", "2026-11-18", line=4)),
    }
    stored(conn, *gs.values())
    return {k: g.id for k, g in gs.items()}


def test_TC_M6_12_overdue_is_derived(conn: sqlite3.Connection, four: dict[str, str]) -> None:
    repo = ItemRepo(conn)
    assert ids(repo.query(ItemFilter(status="overdue"), today=TODAY)) == [four["overdue"]]
    overdue = {r.id for r in repo.query(ItemFilter(), today=TODAY) if r.is_overdue}
    assert overdue == {four["overdue"]}


def test_TC_M6_13_open_includes_overdue(conn: sqlite3.Connection, four: dict[str, str]) -> None:
    rows = ItemRepo(conn).query(ItemFilter(status="open"), today=TODAY)
    assert set(ids(rows)) == {four["overdue"], four["tomorrow"], four["nodue"]}
    done = ItemRepo(conn).query(ItemFilter(status="done"), today=TODAY)
    assert ids(done) == [four["done"]]


def test_TC_M6_14_overdue_moves_with_today(conn: sqlite3.Connection, four: dict[str, str]) -> None:
    later = TODAY + timedelta(days=2)
    rows = ItemRepo(conn).query(ItemFilter(status="overdue"), today=later)
    assert ids(rows) == [four["overdue"], four["tomorrow"]]


def test_TC_M6_18_order(conn: sqlite3.Connection) -> None:
    a = group(src(PRIYA, "a", "2026-11-18", line=1, due="2026-11-30"), owner_display="Zed")
    b = group(src(PRIYA, "b", "2026-11-18", line=2), owner_display="Amy")
    c = group(src(RAHUL, "c", "2026-11-18", line=3, due="2026-11-20"), owner_display="Zed")
    d = group(src(PRIYA, "d", "2026-11-18", line=4, due="2026-11-30"), owner_display="Amy")
    e = group(src(RAHUL, "e", "2026-11-18", line=5), owner_display="Amy")
    stored(conn, a, b, c, d, e)
    rows = ItemRepo(conn).query(ItemFilter(), today=TODAY)
    nulls = sorted([b.id, e.id])
    assert ids(rows) == [c.id, d.id, a.id, *nulls]


def test_TC_M6_19_due_before(conn: sqlite3.Connection) -> None:
    early = group(src(PRIYA, "early", "2026-11-18", line=1, due="2026-11-19"))
    edge = group(src(PRIYA, "edge", "2026-11-18", line=2, due="2026-11-20"))
    none = group(src(PRIYA, "none", "2026-11-18", line=3))
    stored(conn, early, edge, none)
    rows = ItemRepo(conn).query(ItemFilter(due_before=date(2026, 11, 20)), today=TODAY)
    assert ids(rows) == [early.id]


def test_query_owner_unassigned_and_flag(conn: sqlite3.Connection) -> None:
    p = group(src(PRIYA, "p", "2026-11-18", line=1))
    r = group(src(RAHUL, "r", "2026-11-18", line=2))
    u = group(src(None, "u", "2026-11-18", line=3), flags=frozenset({Flag.UNASSIGNED, Flag.NO_DUE}))
    stored(conn, p, r, u)
    repo = ItemRepo(conn)
    assert set(ids(repo.query(ItemFilter(owner_keys=(PRIYA, RAHUL)), today=TODAY))) == {p.id, r.id}
    assert ids(repo.query(ItemFilter(owner_keys=()), today=TODAY)) == []
    assert ids(repo.query(ItemFilter(unassigned=True), today=TODAY)) == [u.id]
    assert ids(repo.query(ItemFilter(flag=Flag.UNASSIGNED), today=TODAY)) == [u.id]
    assert ids(repo.query(ItemFilter(flag=Flag.MULTI_OWNER), today=TODAY)) == []


def test_query_rows_carry_sources(conn: sqlite3.Connection) -> None:
    s1 = src(PRIYA, "Send quote", "2026-11-18", line=4, path="b.md", due="2026-11-20")
    s2 = src(PRIYA, "send the quote", "2026-11-04", line=2, path="a.md")
    g = group(s1, s2)
    stored(conn, g)
    [row] = ItemRepo(conn).query(ItemFilter(), today=TODAY)
    assert row.source_count == 2
    assert row.sources == (
        SourceRef(Path("a.md"), 2, date(2026, 11, 4), None),
        SourceRef(Path("b.md"), 4, date(2026, 11, 18), None),
    )
    assert (row.task, row.task_norm, row.due_date) == (
        "Send quote",
        "send quote",
        date(2026, 11, 20),
    )
    assert (row.first_seen, row.last_seen) == (date(2026, 11, 4), date(2026, 11, 18))


# --- items: apply_groups / existing ----------------------------------------------------------


def test_TC_M6_15_orphaned_hidden_by_default(conn: sqlite3.Connection) -> None:
    s = src(PRIYA, "Send quote", "2026-11-18")
    g = group(s, status="done")
    stored(conn, g)
    NoteRepo(conn).delete(Path("a.md"))
    apply(conn, orphaned=(g.id,))
    repo = ItemRepo(conn)
    assert repo.query(ItemFilter(), today=TODAY) == []
    [row] = repo.query(ItemFilter(flag=Flag.ORPHANED), today=TODAY)
    assert row.id == g.id
    assert row.status == "done"
    assert Flag.ORPHANED in row.flags
    assert row.source_count == 0
    assert ids(repo.query(ItemFilter(include_orphaned=True), today=TODAY)) == [g.id]


def test_TC_M6_16_orphan_regains_source(conn: sqlite3.Connection) -> None:
    s = src(PRIYA, "Send quote", "2026-11-18")
    g = group(s)
    stored(conn, g)
    apply(conn, orphaned=(g.id,))
    apply(conn, orphaned=(g.id,))  # flagging twice keeps one flag
    row = ItemRepo(conn).get(g.id, today=TODAY)
    assert row is not None and row.flags == {Flag.ORPHANED}
    apply(conn, g)
    row = ItemRepo(conn).get(g.id, today=TODAY)
    assert row is not None
    assert Flag.ORPHANED not in row.flags
    assert row.source_count == 1


def test_apply_groups_relinks_sources_and_upserts(conn: sqlite3.Connection) -> None:
    s1 = src(PRIYA, "Send quote", "2026-11-04", line=1, path="a.md")
    s2 = src(PRIYA, "Send quote", "2026-11-18", line=1, path="b.md")
    first = group(s1)
    stored(conn, first, group(s2, item_id="f" * 40))
    merged = group(s1, s2, item_id=first.id, due="2026-12-01")
    apply(conn, merged, orphaned=("f" * 40,))
    repo = ItemRepo(conn)
    row = repo.get(first.id, today=TODAY)
    assert row is not None
    assert row.source_count == 2
    assert row.due_date == date(2026, 12, 1)
    assert repo.ids() == sorted([first.id, "f" * 40])


def test_apply_groups_ignores_unknown_orphan(conn: sqlite3.Connection) -> None:
    apply(conn, orphaned=("0" * 40,))
    assert ItemRepo(conn).ids() == []


def test_existing_collects_norms(conn: sqlite3.Connection) -> None:
    s1 = src(PRIYA, "Send the quote", "2026-11-04", line=1, path="a.md")
    s2 = src(PRIYA, "Send quotes!", "2026-11-18", line=1, path="b.md")
    g = group(s1, s2)
    stored(conn, g)
    ItemRepo(conn).mark_done(g.id, now=NOW)
    [e] = ItemRepo(conn).existing()
    assert e.id == g.id
    assert e.owner_key == PRIYA
    assert e.task_norms == {normalize_task("Send the quote"), "send quotes"}
    assert (e.status, e.done_source, e.done_at) == ("done", "cli", NOW)


def test_existing_orphan_keeps_its_own_norm(conn: sqlite3.Connection) -> None:
    g = group(src(None, "Book room", "2026-11-18"))
    stored(conn, g)
    NoteRepo(conn).delete(Path("a.md"))
    [e] = ItemRepo(conn).existing()
    assert (e.owner_key, e.task_norms, e.done_at) == (None, {"book room"}, None)


# --- items: done / get / ids -----------------------------------------------------------------


def test_TC_M6_17_mark_done(conn: sqlite3.Connection) -> None:
    g = group(src(PRIYA, "Send quote", "2026-11-18"))
    stored(conn, g)
    repo = ItemRepo(conn)
    assert repo.mark_done(g.id, now=NOW) is True
    row = repo.get(g.id, today=TODAY)
    assert row is not None
    assert (row.status, row.done_source, row.done_at) == ("done", "cli", NOW)
    assert repo.mark_done(g.id, now=NOW + timedelta(hours=1)) is False
    row = repo.get(g.id, today=TODAY)
    assert row is not None and row.done_at == NOW


def test_get_unknown_and_overdue(conn: sqlite3.Connection) -> None:
    g = group(src(PRIYA, "Send quote", "2026-11-18", due="2026-11-20"))
    stored(conn, g)
    repo = ItemRepo(conn)
    assert repo.get("0" * 40, today=TODAY) is None
    assert repo.mark_done("0" * 40, now=NOW) is False
    row = repo.get(g.id, today=TODAY)
    assert row is not None and row.is_overdue
    row = repo.get(g.id, today=date(2026, 11, 20))
    assert row is not None and not row.is_overdue


# --- drafts ----------------------------------------------------------------------------------


def test_TC_M6_20_record_draft(conn: sqlite3.Connection) -> None:
    drafts = DraftRepo(conn)
    first = drafts.record(
        owner_key=PRIYA,
        recipient=PRIYA,
        gmail_draft_id="r-1",
        item_ids=["b" * 40, "a" * 40],
        now=NOW,
    )
    second = drafts.record(
        owner_key=RAHUL, recipient=RAHUL, gmail_draft_id=None, item_ids=[], now=NOW
    )
    assert second == first + 1
    r = conn.execute("SELECT * FROM drafts WHERE id = ?", (first,)).fetchone()
    assert (r["owner_key"], r["recipient"], r["gmail_draft_id"]) == (PRIYA, PRIYA, "r-1")
    assert json.loads(r["item_ids"]) == ["b" * 40, "a" * 40]
    assert datetime.fromisoformat(r["created_at"]) == NOW
