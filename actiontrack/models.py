"""Shared data contracts passed between modules (M0 spec §8).

Later modules consume these types. Fields may only be added by changing the M0 spec first.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, Literal

JSON_SCHEMA_VERSION = 1


class Flag(StrEnum):
    UNASSIGNED = "unassigned"
    AMBIGUOUS_OWNER = "ambiguous_owner"
    OWNER_NOT_ATTENDEE = "owner_not_attendee"
    MULTI_OWNER = "multi_owner"
    NO_DUE = "no_due"
    UNPARSED_DUE = "unparsed_due"
    ORPHANED = "orphaned"


class SkipReason(StrEnum):
    EMPTY_FILE = "empty_file"
    BINARY_FILE = "binary_file"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_FRONTMATTER = "invalid_frontmatter"
    MISSING_DATE = "missing_date"
    UNPARSEABLE_DATE = "unparseable_date"
    MISSING_ATTENDEES = "missing_attendees"
    READ_ERROR = "read_error"
    INTERNAL_ERROR = "internal_error"


class WarningCode(StrEnum):
    MALFORMED_CHECKBOX = "malformed_checkbox"
    EMPTY_TASK = "empty_task"


@dataclass(frozen=True, slots=True)
class NoteMeta:
    """M1 output."""

    path: Path
    sha256: str
    meeting_date: date
    title: str | None
    attendees_raw: tuple[str, ...]
    # (1-based line number in file, text) of the body, LF-normalized
    lines: tuple[tuple[int, str], ...]


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """M1 / M7 output."""

    path: Path
    reason: SkipReason
    detail: str
    line_no: int | None = None


@dataclass(frozen=True, slots=True)
class LineWarning:
    """M4 output."""

    path: Path
    line_no: int
    code: WarningCode
    text: str


@dataclass(frozen=True, slots=True)
class Attendee:
    """M2."""

    full_name: str
    first_name: str
    last_name: str | None
    email: str | None  # explicit email from the note
    key: str  # explicit email lowercased | derived email | "name:<first>" (G1)
    derived_email: str | None  # firstname.lastname@domain, None if no last name


@dataclass(frozen=True, slots=True)
class OwnerResolution:
    """M2."""

    owner_key: str | None
    owner_display: str | None
    owner_raw: str | None
    flags: frozenset[Flag]
    candidates: tuple[str, ...]  # candidate keys if ambiguous


@dataclass(frozen=True, slots=True)
class DueResolution:
    """M3."""

    due_date: date | None
    due_raw: str | None
    flags: frozenset[Flag]
    span: tuple[int, int] | None  # char span of the due phrase in the input text


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """M4 output; one per checkbox occurrence ("source")."""

    note_path: Path
    line_no: int
    raw_text: str
    meeting_date: date
    note_title: str | None
    owner: OwnerResolution
    task: str
    due: DueResolution
    checked: bool  # [x] in note
    flags: frozenset[Flag]  # owner.flags | due.flags | item-level flags


@dataclass(frozen=True, slots=True)
class ExistingItem:
    """M6 → M5."""

    id: str
    owner_key: str | None
    task_norms: frozenset[str]
    status: Literal["open", "done"]
    done_source: Literal["note", "cli"] | None
    done_at: datetime | None


@dataclass(frozen=True, slots=True)
class MergeDecision:
    """M5."""

    item_id: str
    kind: Literal["exact", "fuzzy"]
    score: float
    source: tuple[Path, int]
    matched_task_norm: str


@dataclass(frozen=True, slots=True)
class ItemGroup:
    """M5 output → M6."""

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
    sources: tuple[ParsedItem, ...]


@dataclass(frozen=True, slots=True)
class Person:
    """M6 row."""

    key: str
    full_name: str
    first_name: str
    email: str | None


@dataclass(frozen=True, slots=True)
class IngestReport:
    """M7."""

    scanned: int
    ingested: int
    unchanged: int
    removed: int
    skipped: tuple[SkipRecord, ...]
    warnings: tuple[LineWarning, ...]
    sources_total: int
    items_total: int
    exact_merges: int
    fuzzy_merges: int
    flag_counts: Mapping[Flag, int]
    decisions: tuple[MergeDecision, ...]

    def to_json(self) -> dict[str, Any]:
        """A JSON-ready dict: enums as values, dates ISO, paths as POSIX strings."""
        data = to_jsonable(self)
        assert isinstance(data, dict)
        return {"schema_version": JSON_SCHEMA_VERSION, **data}


def to_jsonable(value: Any) -> Any:
    """Recursively convert contracts into plain JSON-serialisable values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(to_jsonable(k)): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, frozenset | set):
        return sorted(to_jsonable(v) for v in value)
    if isinstance(value, tuple | list):
        return [to_jsonable(v) for v in value]
    return value
