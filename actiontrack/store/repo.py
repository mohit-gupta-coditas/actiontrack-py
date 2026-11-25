"""Repositories over the SQLite store, so that services never write SQL (M6 spec §4, §5).

Dates and timestamps are stored as ISO-8601 text and converted here. JSON columns hold arrays of
strings: flag sets sorted, sequences (owner candidates, draft item IDs) in their given order.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from actiontrack.dedup import DedupResult, normalize_task
from actiontrack.models import (
    Attendee,
    DueResolution,
    ExistingItem,
    Flag,
    NoteMeta,
    OwnerResolution,
    ParsedItem,
    Person,
    SkipRecord,
)
from actiontrack.parsing.people import normalize_name
from actiontrack.store.db import transaction

_DUE_FLAGS = frozenset({Flag.NO_DUE, Flag.UNPARSED_DUE})


@dataclass(frozen=True, slots=True)
class NoteRow:
    path: Path
    sha256: str | None
    status: Literal["ok", "skipped"]
    meeting_date: date | None
    title: str | None
    ingested_at: datetime
    skip_reason: str | None
    skip_detail: str | None


@dataclass(frozen=True, slots=True)
class SourceRef:
    path: Path
    line_no: int
    meeting_date: date
    note_title: str | None


@dataclass(frozen=True)
class ItemFilter:
    owner_keys: tuple[str, ...] | None = None
    status: Literal["open", "done", "overdue"] | None = None
    due_before: date | None = None
    unassigned: bool = False
    flag: Flag | None = None
    include_orphaned: bool = False


@dataclass(frozen=True, slots=True)
class ItemRow:
    """`ItemGroup` fields minus the parsed sources, plus derived and per-source data."""

    id: str
    owner_key: str | None
    owner_display: str | None
    owner_raw: str | None
    task: str
    task_norm: str
    due_date: date | None
    due_raw: str | None
    status: Literal["open", "done"]
    done_source: Literal["note", "cli"] | None
    done_at: datetime | None
    flags: frozenset[Flag]
    first_seen: date
    last_seen: date
    source_count: int
    is_overdue: bool
    sources: tuple[SourceRef, ...]


class NoteRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, path: Path) -> NoteRow | None:
        r = self._conn.execute("SELECT * FROM notes WHERE path = ?", (_path(path),)).fetchone()
        if r is None:
            return None
        return NoteRow(
            path=Path(r["path"]),
            sha256=r["sha256"],
            status=r["status"],
            meeting_date=_date(r["meeting_date"]),
            title=r["title"],
            ingested_at=datetime.fromisoformat(r["ingested_at"]),
            skip_reason=r["skip_reason"],
            skip_detail=r["skip_detail"],
        )

    def upsert_ok(self, meta: NoteMeta, *, now: datetime) -> None:
        self._upsert(
            meta.path, meta.sha256, meta.meeting_date.isoformat(), meta.title, now, "ok", None, None
        )

    def upsert_skipped(self, rec: SkipRecord, *, sha256: str | None, now: datetime) -> None:
        """Record a skipped note and drop the sources it had from an earlier ingest."""
        with transaction(self._conn):
            self._upsert(rec.path, sha256, None, None, now, "skipped", rec.reason.value, rec.detail)
            self._conn.execute("DELETE FROM item_sources WHERE note_path = ?", (_path(rec.path),))

    def paths_under(self, root: Path) -> list[Path]:
        """Stored note paths at or below `root` (by path parts: `notes2/` is not under `notes/`)."""
        paths = [Path(r[0]) for r in self._conn.execute("SELECT path FROM notes ORDER BY path")]
        return [p for p in paths if p == root or root in p.parents]

    def delete(self, path: Path) -> None:
        """Delete a note; its sources cascade."""
        self._conn.execute("DELETE FROM notes WHERE path = ?", (_path(path),))

    def _upsert(
        self,
        path: Path,
        sha256: str | None,
        meeting_date: str | None,
        title: str | None,
        now: datetime,
        status: str,
        skip_reason: str | None,
        skip_detail: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO notes (path, sha256, meeting_date, title, ingested_at, status,
                               skip_reason, skip_detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (path) DO UPDATE SET
              sha256 = excluded.sha256, meeting_date = excluded.meeting_date,
              title = excluded.title, ingested_at = excluded.ingested_at,
              status = excluded.status, skip_reason = excluded.skip_reason,
              skip_detail = excluded.skip_detail
            """,
            (_path(path), sha256, meeting_date, title, now.isoformat(), status, skip_reason,
             skip_detail),
        )  # fmt: skip


class SourceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def replace_for_note(self, path: Path, items: Sequence[ParsedItem]) -> None:
        """Replace every stored source of the note at `path` (which must already be stored)."""
        stray = [i for i in items if i.note_path != path]
        if stray:
            raise ValueError(f"source from {stray[0].note_path} passed for note {path}")
        with transaction(self._conn):
            self._conn.execute("DELETE FROM item_sources WHERE note_path = ?", (_path(path),))
            self._conn.executemany(
                """
                INSERT INTO item_sources (note_path, line_no, raw_text, meeting_date, note_title,
                  owner_key, owner_display, owner_raw, owner_flags, owner_candidates,
                  task, due_date, due_raw, checked, flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (_path(i.note_path), i.line_no, i.raw_text, i.meeting_date.isoformat(),
                     i.note_title, i.owner.owner_key, i.owner.owner_display, i.owner.owner_raw,
                     _flags_json(i.owner.flags), json.dumps(list(i.owner.candidates)),
                     i.task, _iso(i.due.due_date), i.due.due_raw, int(i.checked),
                     _flags_json(i.flags))
                    for i in items
                ],
            )  # fmt: skip

    def all(self) -> list[ParsedItem]:
        """Every stored source as a `ParsedItem`, ordered by (meeting_date, path, line_no).

        The due phrase's span is not stored, so `due.span` is None.
        """
        rows = self._conn.execute(
            "SELECT * FROM item_sources ORDER BY meeting_date, note_path, line_no"
        )
        return [_parsed_item(r) for r in rows]

    def count(self) -> int:
        n: int = self._conn.execute("SELECT count(*) FROM item_sources").fetchone()[0]
        return n


class PeopleRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_many(self, attendees: Iterable[Attendee]) -> None:
        """Insert or update by key. A known email is never overwritten by None."""
        self._conn.executemany(
            """
            INSERT INTO people (key, full_name, first_name, email) VALUES (?, ?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
              full_name = excluded.full_name, first_name = excluded.first_name,
              email = coalesce(excluded.email, people.email)
            """,
            [(a.key, a.full_name, a.first_name, a.email or a.derived_email) for a in attendees],
        )

    def find(self, query: str) -> list[Person]:
        """People whose key, email, full name or first name matches `query` (normalized)."""
        q = normalize_name(query)
        if not q:
            return []
        return [
            p
            for p in self._all()
            if q in (p.key.casefold(), (p.email or "").casefold())
            or q in (normalize_name(p.full_name), normalize_name(p.first_name))
        ]

    def get(self, key: str) -> Person | None:
        r = self._conn.execute("SELECT * FROM people WHERE key = ?", (key,)).fetchone()
        return None if r is None else _person(r)

    def _all(self) -> list[Person]:
        return [_person(r) for r in self._conn.execute("SELECT * FROM people ORDER BY key")]


class ItemRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def existing(self) -> list[ExistingItem]:
        """Every stored item, with the norms of its own task and of each source linked to it."""
        norms: dict[str, set[str]] = defaultdict(set)
        for item_id, task in self._conn.execute(
            "SELECT item_id, task FROM item_sources WHERE item_id IS NOT NULL"
        ):
            norms[item_id].add(normalize_task(task))
        rows = self._conn.execute(
            "SELECT id, owner_key, task_norm, status, done_source, done_at FROM items ORDER BY id"
        )
        return [
            ExistingItem(
                id=r["id"],
                owner_key=r["owner_key"],
                task_norms=frozenset(norms[r["id"]] | {r["task_norm"]}),
                status=r["status"],
                done_source=r["done_source"],
                done_at=_datetime(r["done_at"]),
            )
            for r in rows
        ]

    def apply_groups(self, result: DedupResult) -> None:
        """Store a regroup: upsert every group, relink sources, flag the orphaned items.

        Group flags replace the stored ones, so an item that has sources again loses ORPHANED.
        An orphaned item keeps its status and fields.
        """
        with transaction(self._conn):
            self._conn.executemany(
                """
                INSERT INTO items (id, owner_key, owner_display, owner_raw, task, task_norm,
                  due_date, due_raw, status, done_source, done_at, flags, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                  owner_key = excluded.owner_key, owner_display = excluded.owner_display,
                  owner_raw = excluded.owner_raw, task = excluded.task,
                  task_norm = excluded.task_norm, due_date = excluded.due_date,
                  due_raw = excluded.due_raw, status = excluded.status,
                  done_source = excluded.done_source, done_at = excluded.done_at,
                  flags = excluded.flags, first_seen = excluded.first_seen,
                  last_seen = excluded.last_seen
                """,
                [
                    (g.id, g.owner_key, g.owner_display, g.owner_raw, g.task, g.task_norm,
                     _iso(g.due_date), g.due_raw, g.status, g.done_source, _iso(g.done_at),
                     _flags_json(g.flags - {Flag.ORPHANED}), g.first_seen.isoformat(),
                     g.last_seen.isoformat())
                    for g in result.groups
                ],
            )  # fmt: skip
            self._conn.execute("UPDATE item_sources SET item_id = NULL")
            self._conn.executemany(
                "UPDATE item_sources SET item_id = ? WHERE note_path = ? AND line_no = ?",
                [(g.id, _path(s.note_path), s.line_no) for g in result.groups for s in g.sources],
            )
            for item_id in result.orphaned_ids:
                r = self._conn.execute(
                    "SELECT flags FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                if r is not None:
                    flags = _flags(r["flags"]) | {Flag.ORPHANED}
                    self._conn.execute(
                        "UPDATE items SET flags = ? WHERE id = ?", (_flags_json(flags), item_id)
                    )

    def query(self, f: ItemFilter, *, today: date) -> list[ItemRow]:
        sql, params = self._select_sql(f, today=today)
        rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            return []
        sources: dict[str, list[SourceRef]] = defaultdict(list)
        for r in self._conn.execute(
            f"""
            SELECT item_id, note_path, line_no, meeting_date, note_title FROM item_sources
            WHERE item_id IN (SELECT id FROM ({sql}))
            ORDER BY meeting_date, note_path, line_no
            """,
            params,
        ):
            sources[r["item_id"]].append(_source_ref(r))
        return [_item_row(r, sources[r["id"]]) for r in rows]

    def ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT id FROM items ORDER BY id")]

    def get(self, item_id: str, *, today: date) -> ItemRow | None:
        """One item by full ID, orphaned or not."""
        r = self._conn.execute(
            f"SELECT *, {_OVERDUE_SQL} AS is_overdue FROM items WHERE id = :id",
            {"id": item_id, "today": today.isoformat()},
        ).fetchone()
        if r is None:
            return None
        refs = self._conn.execute(
            """
            SELECT note_path, line_no, meeting_date, note_title FROM item_sources
            WHERE item_id = ? ORDER BY meeting_date, note_path, line_no
            """,
            (item_id,),
        )
        return _item_row(r, [_source_ref(s) for s in refs])

    def mark_done(self, item_id: str, *, now: datetime) -> bool:
        """Mark an open item done from the CLI. False if it is already done (or unknown)."""
        cur = self._conn.execute(
            """
            UPDATE items SET status = 'done', done_source = 'cli', done_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (now.isoformat(), item_id),
        )
        return cur.rowcount == 1

    def _select_sql(self, f: ItemFilter, *, today: date) -> tuple[str, dict[str, Any]]:
        where: list[str] = []
        params: dict[str, Any] = {"today": today.isoformat()}
        if f.owner_keys is not None:
            names = [f":owner{i}" for i in range(len(f.owner_keys))]
            where.append(f"owner_key IN ({', '.join(names)})")
            params.update({n[1:]: k for n, k in zip(names, f.owner_keys, strict=True)})
        if f.status == "overdue":
            where.append("status = 'open' AND due_date IS NOT NULL AND due_date < :today")
        elif f.status is not None:
            where.append("status = :status")
            params["status"] = f.status
        if f.due_before is not None:
            where.append("due_date IS NOT NULL AND due_date < :due_before")
            params["due_before"] = f.due_before.isoformat()
        if f.unassigned:
            where.append("owner_key IS NULL")
        if f.flag is not None:
            where.append(_HAS_FLAG_SQL.format(param=":flag"))
            params["flag"] = f.flag.value
        if not f.include_orphaned and f.flag != Flag.ORPHANED:
            where.append("NOT " + _HAS_FLAG_SQL.format(param="'orphaned'"))
        sql = f"SELECT *, {_OVERDUE_SQL} AS is_overdue FROM items"
        if where:
            sql += " WHERE " + " AND ".join(f"({w})" for w in where)
        sql += " ORDER BY due_date IS NULL, due_date, owner_display, id"
        return sql, params


class DraftRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(
        self,
        *,
        owner_key: str,
        recipient: str,
        gmail_draft_id: str | None,
        item_ids: Sequence[str],
        now: datetime,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO drafts (owner_key, recipient, gmail_draft_id, created_at, item_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (owner_key, recipient, gmail_draft_id, now.isoformat(), json.dumps(list(item_ids))),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


_OVERDUE_SQL = "(status = 'open' AND due_date IS NOT NULL AND due_date < :today)"
_HAS_FLAG_SQL = "EXISTS (SELECT 1 FROM json_each(items.flags) WHERE value = {param})"


def _path(p: Path) -> str:
    return p.as_posix()


def _iso(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def _date(s: str | None) -> date | None:
    return None if s is None else date.fromisoformat(s)


def _datetime(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


def _flags_json(flags: Iterable[Flag]) -> str:
    return json.dumps(sorted(f.value for f in flags))


def _flags(s: str) -> frozenset[Flag]:
    return frozenset(Flag(v) for v in json.loads(s))


def _person(r: sqlite3.Row) -> Person:
    return Person(
        key=r["key"], full_name=r["full_name"], first_name=r["first_name"], email=r["email"]
    )


def _source_ref(r: sqlite3.Row) -> SourceRef:
    return SourceRef(
        path=Path(r["note_path"]),
        line_no=r["line_no"],
        meeting_date=date.fromisoformat(r["meeting_date"]),
        note_title=r["note_title"],
    )


def _parsed_item(r: sqlite3.Row) -> ParsedItem:
    flags = _flags(r["flags"])
    return ParsedItem(
        note_path=Path(r["note_path"]),
        line_no=r["line_no"],
        raw_text=r["raw_text"],
        meeting_date=date.fromisoformat(r["meeting_date"]),
        note_title=r["note_title"],
        owner=OwnerResolution(
            owner_key=r["owner_key"],
            owner_display=r["owner_display"],
            owner_raw=r["owner_raw"],
            flags=_flags(r["owner_flags"]),
            candidates=tuple(json.loads(r["owner_candidates"])),
        ),
        task=r["task"],
        due=DueResolution(
            due_date=_date(r["due_date"]),
            due_raw=r["due_raw"],
            flags=flags & _DUE_FLAGS,
            span=None,
        ),
        checked=bool(r["checked"]),
        flags=flags,
    )


def _item_row(r: sqlite3.Row, sources: list[SourceRef]) -> ItemRow:
    return ItemRow(
        id=r["id"],
        owner_key=r["owner_key"],
        owner_display=r["owner_display"],
        owner_raw=r["owner_raw"],
        task=r["task"],
        task_norm=r["task_norm"],
        due_date=_date(r["due_date"]),
        due_raw=r["due_raw"],
        status=r["status"],
        done_source=r["done_source"],
        done_at=_datetime(r["done_at"]),
        flags=_flags(r["flags"]),
        first_seen=date.fromisoformat(r["first_seen"]),
        last_seen=date.fromisoformat(r["last_seen"]),
        source_count=len(sources),
        is_overdue=bool(r["is_overdue"]),
        sources=tuple(sources),
    )
