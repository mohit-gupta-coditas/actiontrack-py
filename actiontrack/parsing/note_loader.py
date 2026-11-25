"""Load one markdown note into a `NoteMeta` or a `SkipRecord` (M1 spec).

Never raises for content problems: every unusable note becomes a `SkipRecord` with a reason.
The file is only ever read (REQ-GEN-03).
"""

from __future__ import annotations

import codecs
import hashlib
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from actiontrack.models import NoteMeta, SkipReason, SkipRecord

DateOrder = Literal["DMY", "MDY"]

_BINARY_SNIFF_BYTES = 8192
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_LINE = re.compile(r"^\s*\**date\**\s*:\s*\**\s*(.+?)\s*$", re.IGNORECASE)
_ATTENDEES_LINE = re.compile(
    r"^\s*\**(?:attendees|participants)\**\s*:\s*\**\s*(.*?)\s*$", re.IGNORECASE
)
_ATTENDEES_HEADING = re.compile(
    r"^\s*#{1,6}\s+\**(?:attendees|participants)\**\s*:?\s*$", re.IGNORECASE
)
_HEADING = re.compile(r"^\s*#{1,6}\s")
_H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*?)\s*$")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[[ xX]\]")
_LIST_SEPARATORS = re.compile(r"[,;]")
_TITLE_SEPARATORS = " \t\u2014\u2013-:|"  # em dash, en dash, hyphen, colon, pipe
_TITLE_LABEL = re.compile(r"^\s*(?:meeting|notes)\s*:", re.IGNORECASE)  # "Meeting: QA sync" (G37)

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
# A date-like substring inside an H1. The year is optional for month-name forms so that
# "Sync — 18 Nov" reports UNPARSEABLE_DATE (with the raw value) rather than MISSING_DATE.
_H1_DATE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+\d{{4}})?\b"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b",
    re.IGNORECASE,
)


def load_note(path: Path, *, date_order: DateOrder = "DMY") -> NoteMeta | SkipRecord:
    """Read and parse one note. Content problems come back as a `SkipRecord`."""

    def skip(reason: SkipReason, detail: str, line_no: int | None = None) -> SkipRecord:
        return SkipRecord(path=path, reason=reason, detail=detail, line_no=line_no)

    try:
        raw = path.read_bytes()
    except OSError as e:
        return skip(SkipReason.READ_ERROR, str(e))
    if not raw:
        return skip(SkipReason.EMPTY_FILE, "file is empty")
    if b"\x00" in raw[:_BINARY_SNIFF_BYTES]:
        return skip(SkipReason.BINARY_FILE, "file contains NUL bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        offset = e.start + (len(codecs.BOM_UTF8) if raw.startswith(codecs.BOM_UTF8) else 0)
        return skip(SkipReason.INVALID_ENCODING, f"not valid UTF-8 at byte offset {offset}")
    if not text.strip():
        return skip(SkipReason.EMPTY_FILE, "file contains only whitespace")

    sha256 = hashlib.sha256(raw).hexdigest()
    all_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if all_lines[-1] == "":
        all_lines.pop()

    # Frontmatter (only if line 1 is a fence)
    front: dict[Any, Any] = {}
    body_start = 0
    if all_lines and all_lines[0].rstrip() == "---":
        close = next(
            (i for i in range(1, len(all_lines)) if all_lines[i].rstrip() in ("---", "...")),
            None,
        )
        if close is None:
            return skip(SkipReason.INVALID_FRONTMATTER, "frontmatter has no closing fence", 1)
        try:
            loaded = yaml.safe_load("\n".join(all_lines[1:close]))
        except yaml.MarkedYAMLError as e:
            mark = e.problem_mark or e.context_mark
            line_no = mark.line + 2 if mark is not None else 1
            return skip(SkipReason.INVALID_FRONTMATTER, f"YAML error: {e.problem}", line_no)
        except (yaml.YAMLError, ValueError, TypeError) as e:
            return skip(SkipReason.INVALID_FRONTMATTER, f"YAML error: {e}", 1)
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            return skip(
                SkipReason.INVALID_FRONTMATTER,
                f"frontmatter is a {type(loaded).__name__}, not a mapping",
                1,
            )
        front = loaded
        body_start = close + 1

    lines = tuple((i + 1, all_lines[i]) for i in range(body_start, len(all_lines)))
    scan = _scan_body(lines)

    # Meeting date: frontmatter → Date: line → H1
    date_raw: str | None = None
    meeting_date: date | None = None
    fm_date = front.get("date")
    if isinstance(fm_date, datetime):
        meeting_date = fm_date.date()
    elif isinstance(fm_date, date):
        meeting_date = fm_date
    elif fm_date is not None and str(fm_date).strip():
        date_raw = str(fm_date).strip()
    elif scan.date_line is not None:
        date_raw = scan.date_line
    elif scan.h1_date is not None:
        date_raw = scan.h1_date
    else:
        return skip(SkipReason.MISSING_DATE, "no meeting date in frontmatter, Date: line or H1")
    if meeting_date is None:
        assert date_raw is not None
        meeting_date = parse_meeting_date(date_raw, date_order=date_order)
        if meeting_date is None:
            return skip(SkipReason.UNPARSEABLE_DATE, f"cannot parse meeting date {date_raw!r}")

    title = _title(front.get("title"), scan.h1)

    # Attendees: frontmatter → inline line → heading list
    attendees = _clean(_frontmatter_list(front.get("attendees")))
    if not attendees:
        attendees = _clean(_frontmatter_list(front.get("participants")))
    if not attendees and scan.attendees_line is not None:
        attendees = _clean(_LIST_SEPARATORS.split(scan.attendees_line))
    if not attendees:
        attendees = _clean(scan.attendees_bullets)
    if not attendees:
        return skip(SkipReason.MISSING_ATTENDEES, "no attendees listed")

    return NoteMeta(
        path=path,
        sha256=sha256,
        meeting_date=meeting_date,
        title=title,
        attendees_raw=attendees,
        lines=lines,
    )


def parse_meeting_date(text: str, *, date_order: DateOrder) -> date | None:
    """ISO `YYYY-MM-DD` first, then strict `dateparser` (day, month and year). Never raises."""
    iso = _ISO_DATE.search(text)
    if iso is not None:
        try:
            return date.fromisoformat(iso.group())
        except ValueError:
            return None
    try:
        import dateparser  # slow import; only needed for non-ISO dates

        parsed = dateparser.parse(
            text,
            settings={
                "STRICT_PARSING": True,
                "DATE_ORDER": date_order,
                "PREFER_DAY_OF_MONTH": "first",
                "REQUIRE_PARTS": ["day", "month", "year"],
                # No relative dates ("tomorrow"): a meeting date must not depend on the clock
                "PARSERS": ["absolute-time"],
            },
        )
    except Exception:
        return None
    return parsed.date() if parsed is not None else None


class _BodyScan:
    """What one pass over the body found. Each field holds the first occurrence only."""

    __slots__ = ("attendees_bullets", "attendees_line", "date_line", "h1", "h1_date")

    def __init__(self) -> None:
        self.date_line: str | None = None
        self.h1: str | None = None
        self.h1_date: str | None = None
        self.attendees_line: str | None = None
        self.attendees_bullets: list[str] = []


def _scan_body(lines: Iterable[tuple[int, str]]) -> _BodyScan:
    scan = _BodyScan()
    seen_checkbox = False
    # Heading-list state: None = not in one, "before" = waiting for bullets, "in" = reading them,
    # "done" = the first attendees heading list has been read.
    heading_list: str | None = None

    for _, line in lines:
        if heading_list in ("before", "in"):
            bullet = _BULLET.match(line)
            if bullet is not None and not _HEADING.match(line):
                scan.attendees_bullets.append(bullet.group(1))
                heading_list = "in"
                continue
            if not line.strip() and heading_list == "before":
                continue
            heading_list = "done"

        if _CHECKBOX.match(line):
            seen_checkbox = True
        elif not seen_checkbox and scan.date_line is None:
            m = _DATE_LINE.match(line)
            if m is not None:
                scan.date_line = m.group(1).strip("* ")

        h1 = _H1.match(line)
        if h1 is not None:
            if scan.h1 is None:
                scan.h1 = h1.group(1)
            if scan.h1_date is None:
                found = _H1_DATE.search(h1.group(1))
                if found is not None:
                    scan.h1_date = found.group()

        if scan.attendees_line is None:
            m = _ATTENDEES_LINE.match(line)
            if m is not None and m.group(1).strip("* "):
                scan.attendees_line = m.group(1).strip("* ")

        if heading_list is None and _ATTENDEES_HEADING.match(line):
            heading_list = "before"

    return scan


def _title(fm_title: Any, h1: str | None) -> str | None:
    if fm_title is not None and str(fm_title).strip():
        return str(fm_title).strip()
    if h1 is None:
        return None
    h1 = _TITLE_LABEL.sub("", h1, count=1)
    found = _H1_DATE.search(h1)
    if found is None:
        title = h1.strip(_TITLE_SEPARATORS)
    else:
        left = h1[: found.start()].rstrip(_TITLE_SEPARATORS)
        right = h1[found.end() :].lstrip(_TITLE_SEPARATORS)
        title = " ".join(part for part in (left, right) if part).strip(_TITLE_SEPARATORS)
    return title or None


def _frontmatter_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _LIST_SEPARATORS.split(value)
    if isinstance(value, list | tuple):
        return [str(v) for v in value if v is not None and not isinstance(v, dict | list)]
    return [str(value)]


def _clean(entries: Iterable[str]) -> tuple[str, ...]:
    return tuple(e.strip() for e in entries if e.strip())
