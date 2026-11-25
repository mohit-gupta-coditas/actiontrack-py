"""The `list` and `done` use cases: filtered views of stored items, and marking one done (M8)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Literal

from actiontrack.clock import Clock
from actiontrack.dedup import resolve_prefix, shortest_unique_prefixes
from actiontrack.errors import UserInputError
from actiontrack.models import Flag, Person
from actiontrack.parsing.dates import DateOrder, parse_user_date
from actiontrack.store.repo import ItemFilter, ItemRepo, ItemRow, PeopleRepo, SourceRef

Status = Literal["open", "done", "overdue"]
STATUSES: tuple[Status, ...] = ("open", "done", "overdue")


@dataclass(frozen=True)
class ItemView:
    id: str
    short_id: str
    owner_key: str | None
    owner_display: str | None
    owner_raw: str | None
    task: str
    due_date: date | None
    status: Status
    flags: tuple[str, ...]
    sources: tuple[SourceRef, ...]


def resolve_owner_query(q: str, people: PeopleRepo) -> Person:
    """The one person matching `q` (key, email, full or first name). Reused by `followup`."""
    text = q.strip()
    matches = people.find(text)
    if not matches:
        raise UserInputError(
            f'no person matches "{text}"', hint="use a name or email from the notes' attendees"
        )
    if len(matches) > 1:
        candidates = ", ".join(f"{p.full_name} <{p.email or p.key}>" for p in matches)
        raise UserInputError(
            f'"{text}" matches {len(matches)} people',
            hint=f"{candidates} — use full name or email",
        )
    return matches[0]


def list_items(
    conn: sqlite3.Connection,
    *,
    owner: str | None = None,
    status: str | None = None,
    due_before: str | None = None,
    unassigned: bool = False,
    flag: str | None = None,
    clock: Clock,
    date_order: DateOrder = "DMY",
) -> list[ItemView]:
    """Items matching every given filter. No `status` means open (overdue included).

    Orphaned items are only listed with `flag="orphaned"` (G3).
    """
    if owner is not None and unassigned:
        raise UserInputError(
            "--owner and --unassigned cannot be used together",
            hint="an unassigned item has no owner; pick one of the two",
        )
    if status is not None and status not in STATUSES:
        raise UserInputError(f'invalid status "{status}"', hint="use open, done or overdue")
    flag_ = _flag(flag)
    owner_keys = None
    if owner is not None:
        owner_keys = (resolve_owner_query(owner, PeopleRepo(conn)).key,)
    today = clock.today()
    before = None
    if due_before is not None:
        before = parse_user_date(due_before, today=today, date_order=date_order)
    f = ItemFilter(
        owner_keys=owner_keys,
        status=status or "open",
        due_before=before,
        unassigned=unassigned,
        flag=flag_,
        include_orphaned=flag_ is Flag.ORPHANED,
    )
    items = ItemRepo(conn)
    rows = items.query(f, today=today)
    if not rows:
        return []
    short_ids = shortest_unique_prefixes(items.ids())
    return [_view(r, short_ids[r.id]) for r in rows]


def mark_done(conn: sqlite3.Connection, prefix: str, *, clock: Clock) -> tuple[ItemView, bool]:
    """Mark the item whose ID starts with `prefix` done. `changed` is False if it already was."""
    items = ItemRepo(conn)
    ids = items.ids()
    item_id = resolve_prefix(prefix, ids)
    changed = items.mark_done(item_id, now=clock.now())
    row = items.get(item_id, today=clock.today())
    assert row is not None
    return _view(row, shortest_unique_prefixes(ids)[item_id]), changed


def _flag(value: str | None) -> Flag | None:
    if value is None:
        return None
    try:
        return Flag(value)
    except ValueError:
        names = ", ".join(f.value for f in Flag)
        raise UserInputError(f'invalid flag "{value}"', hint=f"use one of: {names}") from None


def _view(r: ItemRow, short_id: str) -> ItemView:
    return ItemView(
        id=r.id,
        short_id=short_id,
        owner_key=r.owner_key,
        owner_display=r.owner_display,
        owner_raw=r.owner_raw,
        task=r.task,
        due_date=r.due_date,
        status="overdue" if r.is_overdue else r.status,
        flags=tuple(sorted(f.value for f in r.flags)),
        sources=r.sources,
    )
