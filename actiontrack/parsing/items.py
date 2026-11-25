"""Action-item extraction: checkbox lines → owner / task / due (M4 spec).

Each checkbox line becomes one `ParsedItem`. A line that looks like a broken checkbox becomes a
`LineWarning` instead, and everything else in the note is ordinary text.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from actiontrack.models import (
    Flag,
    LineWarning,
    NoteMeta,
    ParsedItem,
    WarningCode,
)
from actiontrack.parsing.dates import DateOrder, extract_due
from actiontrack.parsing.people import Roster

_FENCE = re.compile(r"^\s*(?:```|~~~)")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[(?P<marker>[ xX])\]\s+(?P<body>\S.*)$")
_EMPTY_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[[ xX]\]\s*$")
_MALFORMED = (
    re.compile(r"^\s*[-*+]\[[ xX]?\]"),  # no space after the bullet: `-[ ] ...`
    re.compile(r"^\s*[-*+]\s+\[\]"),  # empty brackets: `- [] ...`
    re.compile(r"^\s*\[[ xX]\]\s+\S"),  # no bullet: `[ ] ...`
    re.compile(r"^\s*[-*+]\s+\[[^ xX\]]\]"),  # unknown marker: `- [-] ...`
)

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
# `*` / `_` runs used as emphasis: not between two word characters, so `rahul_mehta` is kept.
_EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")

# `and` is only ever a separator; letting a name contain it makes the match backtrack exponentially.
_NAME = r"@?[\w.'-]+(?:\s+(?!and\b)[\w.'-]+){0,2}?"
_OWNER_SEPARATOR = r"\s*,\s*|\s*&\s*|\s+and\s+"
_LEADING_OWNER = re.compile(
    rf"^(?P<owner>{_NAME}(?:(?:{_OWNER_SEPARATOR}){_NAME})*)\s*"
    "(?P<conn>:|\u2014|\u2013| - |"  # colon, em dash, en dash, spaced hyphen, or a verb
    r"\s+(?:to|will|should|must|needs to|is to|to\s+be)\b)\s*(?P<rest>.+)$"
)
_SPLIT_OWNERS = re.compile(_OWNER_SEPARATOR)
_MENTION = re.compile(r"(?<![\w.@])@(?P<handle>\w[\w.'-]*\w|\w)")
# Brackets left empty once the due phrase is taken out: `book venue (due 2026-12-01)`.
_EMPTY_BRACKETS = re.compile(r"[(\[]\s*[)\]]")
_TASK_EDGES = " \t,;:-\u2013\u2014"


class CheckboxLine(NamedTuple):
    checked: bool
    body: str


class MalformedCheckbox(NamedTuple):
    code: WarningCode


class OwnerSplit(NamedTuple):
    owner_raw: str | None
    rest: str  # the text without the owner and its connector
    multi_owner: bool


def extract_items(
    note: NoteMeta, roster: Roster, *, date_order: DateOrder = "DMY"
) -> tuple[list[ParsedItem], list[LineWarning]]:
    """Every action item in the note, in line order, plus a warning per malformed checkbox."""
    items: list[ParsedItem] = []
    warnings: list[LineWarning] = []
    in_fence = False
    for line_no, line in note.lines:
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        kind = classify_line(line)
        if kind is None:
            continue
        if isinstance(kind, MalformedCheckbox):
            warnings.append(LineWarning(note.path, line_no, kind.code, line.strip()))
            continue

        split = split_owner(clean_inline_markdown(kind.body))
        due = extract_due(split.rest, anchor=note.meeting_date, date_order=date_order)
        rest = split.rest
        if due.span is not None:
            start, end = due.span
            rest = rest[:start] + " " + rest[end:]
        task = _tidy_task(rest)
        if not task:
            warnings.append(LineWarning(note.path, line_no, WarningCode.EMPTY_TASK, line.strip()))
            continue

        owner = roster.resolve(split.owner_raw)
        flags = owner.flags | due.flags
        if split.multi_owner:
            flags |= {Flag.MULTI_OWNER}
        items.append(
            ParsedItem(
                note_path=note.path,
                line_no=line_no,
                raw_text=line.strip(),
                meeting_date=note.meeting_date,
                note_title=note.title,
                owner=owner,
                task=task,
                due=due,
                checked=kind.checked,
                flags=flags,
            )
        )
    return items, warnings


def classify_line(line: str) -> CheckboxLine | MalformedCheckbox | None:
    """A checkbox, a broken checkbox, or None for ordinary text."""
    if m := _CHECKBOX.match(line):
        return CheckboxLine(checked=m.group("marker") in "xX", body=m.group("body"))
    if _EMPTY_CHECKBOX.match(line):
        return MalformedCheckbox(WarningCode.EMPTY_TASK)
    if any(p.match(line) for p in _MALFORMED):
        return MalformedCheckbox(WarningCode.MALFORMED_CHECKBOX)
    return None


def clean_inline_markdown(s: str) -> str:
    """Drop emphasis markers and backticks, turn `[text](url)` into `text`, collapse whitespace."""
    s = _LINK.sub(r"\1", s)
    s = _EMPHASIS.sub("", s.replace("`", ""))
    return " ".join(s.split())


def split_owner(body: str) -> OwnerSplit:
    """Take the owner off the front of an item (`Priya to ...`), else the first `@mention`."""
    if m := _LEADING_OWNER.match(body):
        owners = _SPLIT_OWNERS.split(m.group("owner"))
        if all(_is_name(o) for o in owners):
            rest = m.group("rest")
            # A label such as `Sub-task: Priya will check numbers`: the owner is the inner one.
            if m.group("conn") == ":":
                inner = _LEADING_OWNER.match(rest)
                if inner and inner.group("conn") != ":" and (nested := split_owner(rest)).owner_raw:
                    return nested
            return OwnerSplit(owners[0], rest, multi_owner=len(owners) > 1)
    if m := _MENTION.search(body):
        rest = " ".join((body[: m.start()] + body[m.end() :]).split())
        return OwnerSplit(f"@{m.group('handle')}", rest, multi_owner=False)
    return OwnerSplit(None, body, multi_owner=False)


def _is_name(owner: str) -> bool:
    """Every token starts with an uppercase letter or `@`: `send the deck to Rahul` has no owner."""
    return all(t[0] == "@" or t[0].isupper() for t in owner.split())


def _tidy_task(rest: str) -> str:
    task = _EMPTY_BRACKETS.sub("", rest)
    task = " ".join(task.split()).strip(_TASK_EDGES)
    return task.removesuffix(".").strip(_TASK_EDGES)
