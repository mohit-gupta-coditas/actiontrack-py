"""Test builders shared by the unit tests: hand-built `ParsedItem` sources."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from actiontrack.models import DueResolution, Flag, OwnerResolution, ParsedItem


def owner(key: str | None, *, candidates: tuple[str, ...] = ()) -> OwnerResolution:
    """An owner resolved to `key`, unassigned for None, or ambiguous between `candidates`."""
    if candidates:
        flags = frozenset({Flag.AMBIGUOUS_OWNER})
    elif key is None:
        flags = frozenset({Flag.UNASSIGNED})
    else:
        flags = frozenset()
    display = key.split("@")[0] if key else None
    return OwnerResolution(key, display, display, flags, candidates)


def src(
    owner_: str | OwnerResolution | None,
    task: str,
    meeting: str | date,
    line: int = 1,
    due: str | date | None = None,
    checked: bool = False,
    path: str = "a.md",
    due_raw: str | None = None,
) -> ParsedItem:
    """One source. `due` is the resolved date; `due_raw` alone makes an unparsed phrase."""
    o = owner_ if isinstance(owner_, OwnerResolution) else owner(owner_)
    due_date = date.fromisoformat(due) if isinstance(due, str) else due
    if due_date is not None:
        d = DueResolution(due_date, due_raw or f"by {due_date.isoformat()}", frozenset(), None)
    elif due_raw is not None:
        d = DueResolution(None, due_raw, frozenset({Flag.UNPARSED_DUE}), None)
    else:
        d = DueResolution(None, None, frozenset({Flag.NO_DUE}), None)
    return ParsedItem(
        note_path=Path(path),
        line_no=line,
        raw_text=f"- [{'x' if checked else ' '}] {task}",
        meeting_date=date.fromisoformat(meeting) if isinstance(meeting, str) else meeting,
        note_title=None,
        owner=o,
        task=task,
        due=d,
        checked=checked,
        flags=o.flags | d.flags,
    )
