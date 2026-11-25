"""Test builders for the parsing tests: in-memory notes and rosters."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from actiontrack.models import NoteMeta
from actiontrack.parsing.people import Roster, build_roster

DOMAIN = "coditas.com"
MEETING_DATE = date(2026, 11, 18)  # a Wednesday
NOTE_PATH = Path("notes/sync.md")


def make_note(
    *body_lines: str,
    first_line_no: int = 1,
    meeting_date: date = MEETING_DATE,
    title: str | None = "Weekly sync",
    path: Path = NOTE_PATH,
) -> NoteMeta:
    """A `NoteMeta` whose body is `body_lines`, numbered from `first_line_no`."""
    return NoteMeta(
        path=path,
        sha256="0" * 64,
        meeting_date=meeting_date,
        title=title,
        attendees_raw=(),
        lines=tuple(enumerate(body_lines, start=first_line_no)),
    )


def make_roster(*attendees_raw: str) -> Roster:
    """A roster from raw attendee strings; [Priya Shah, Rahul Mehta] by default."""
    return build_roster(attendees_raw or ("Priya Shah", "Rahul Mehta"), domain=DOMAIN)
