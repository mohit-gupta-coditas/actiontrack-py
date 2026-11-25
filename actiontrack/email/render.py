"""Follow-up email rendering: one person's overdue and open items → subject and body (M9 spec).

`render_followup` is deterministic: the same inputs always give the same bytes (D5). The only I/O
is loading the packaged template.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import jinja2

_TEMPLATE = "followup.txt.j2"


@dataclass(frozen=True)
class EmailItem:
    short_id: str
    task: str
    due_date: date | None
    meeting_title: str | None
    meeting_date: date  # most recent source


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body: str


@dataclass(frozen=True)
class _Row:
    """An item as the template sees it: dates already in ISO form."""

    short_id: str
    task: str
    due: str | None
    days: int | None  # days overdue; None for open items
    meeting_title: str | None
    meeting_date: str


def render_followup(
    *,
    first_name: str,
    overdue: Sequence[EmailItem],
    open_: Sequence[EmailItem],
    today: date,
    sign_off: str,
) -> RenderedEmail:
    if not overdue and not open_:
        raise ValueError("a follow-up needs at least one overdue or open item")
    for it in overdue:
        if it.due_date is None or it.due_date >= today:
            raise ValueError(f"item {it.short_id} is not overdue on {today.isoformat()} (G13)")

    overdue_rows = [
        _row(it, today)
        for it in sorted(overdue, key=lambda it: (it.due_date or date.max, it.short_id))
    ]
    open_rows = [
        _row(it, None)
        for it in sorted(
            open_, key=lambda it: (it.due_date is None, it.due_date or date.max, it.short_id)
        )
    ]
    text = _template().render(
        first_name=first_name, overdue=overdue_rows, open=open_rows, sign_off=sign_off
    )
    return RenderedEmail(_subject(len(open_), len(overdue)), _normalize(text))


def _subject(n_open: int, n_overdue: int) -> str:
    counts = f"{n_open} open, {n_overdue} overdue" if n_overdue else f"{n_open} open"
    return f"Follow-up: your open action items ({counts})"


def _row(it: EmailItem, today: date | None) -> _Row:
    days = (today - it.due_date).days if today is not None and it.due_date is not None else None
    return _Row(
        short_id=it.short_id,
        task=it.task,
        due=it.due_date.isoformat() if it.due_date else None,
        days=days,
        meeting_title=it.meeting_title,
        meeting_date=it.meeting_date.isoformat(),
    )


def _normalize(text: str) -> str:
    """Right-strip every line and end with exactly one newline (G14)."""
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


@functools.cache
def _template() -> jinja2.Template:
    import jinja2  # slow import; only needed when an email is rendered

    env = jinja2.Environment(
        loader=jinja2.PackageLoader("actiontrack", "templates"),
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    return env.get_template(_TEMPLATE)
