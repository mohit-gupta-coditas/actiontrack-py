"""Due-phrase detection and due-date resolution (M3 spec).

Relative expressions (weekdays, EOW, next week, ...) follow our own deterministic rules, anchored on
the meeting date. Only calendar dates such as `12 Dec` or `03/04/2027` go to `dateparser`.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import Literal, NamedTuple

from actiontrack.errors import UserInputError
from actiontrack.models import DueResolution, Flag

DateOrder = Literal["DMY", "MDY"]

_WEEKDAY = (
    r"mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?"
    r"|sat(?:urday)?|sun(?:day)?"
)
_MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_WEEKDAY_INDEX = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}

# The expression after a connector: up to the first `,` `;` `(` or ` - `.
_EXPR = r"(?P<expr>(?:(?! - )[^,;(])+)"
_CONNECTOR = re.compile(
    rf"\b(?:by|before|due(?:\s+on|\s+by)?|until|no\s+later\s+than|deadline:?)\s+{_EXPR}",
    re.IGNORECASE,
)
# `on` only before something date-like, so `work on the deck` is not a due phrase.
_ON = re.compile(rf"\bon\s+(?=(?:{_WEEKDAY}|{_MONTH})\b|\d){_EXPR}", re.IGNORECASE)
_KEYWORD = re.compile(
    r"\b(?:eod|eow|eom|end\s+of\s+(?:the\s+)?(?:day|week|month)|end\s+of\s+next\s+week"
    r"|tomorrow|today|next\s+week|asap)\b",
    re.IGNORECASE,
)
_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TRAILING = " \t.!"

_ISO_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEKDAY_EXPR = re.compile(rf"^(?:(this|next)\s+)?({_WEEKDAY})$")
_MONTH_WORD = re.compile(rf"\b(?:{_MONTH})\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b")
_HAS_YEAR = re.compile(r"\b\d{4}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")


class _Phrase(NamedTuple):
    start: int
    end: int
    expr: str
    # Keywords, ISO dates and `on` phrases give way to a longer phrase that ends at the same place,
    # so `by tomorrow` and `due on 3 Dec` are kept whole.
    yields: bool


def extract_due(text: str, *, anchor: date, date_order: DateOrder = "DMY") -> DueResolution:
    """Find the due phrase in an action item (the last one wins) and resolve it from `anchor`."""
    phrase = _pick(_find_phrases(text))
    if phrase is None:
        return DueResolution(None, None, frozenset({Flag.NO_DUE}), None)
    due_date = resolve_expr(phrase.expr, anchor=anchor, date_order=date_order)
    return DueResolution(
        due_date=due_date,
        due_raw=text[phrase.start : phrase.end],
        flags=frozenset() if due_date else frozenset({Flag.UNPARSED_DUE}),
        span=(phrase.start, phrase.end),
    )


def resolve_expr(expr: str, *, anchor: date, date_order: DateOrder = "DMY") -> date | None:
    """Resolve a due expression (`Friday`, `EOW`, `12 Dec`, ...). None when it is not a date."""
    return _resolve(expr, anchor=anchor, date_order=date_order, weekday_on_anchor=False)


def parse_user_date(text: str, *, today: date, date_order: DateOrder = "DMY") -> date:
    """A date typed by the user (`list --due-before`). A weekday may be today."""
    resolved = _resolve(text, anchor=today, date_order=date_order, weekday_on_anchor=True)
    if resolved is None:
        raise UserInputError(f'could not understand date "{text.strip()}"', hint="use YYYY-MM-DD")
    return resolved


def _find_phrases(text: str) -> list[_Phrase]:
    phrases: list[_Phrase] = []
    for pattern, yields in ((_CONNECTOR, False), (_ON, True)):
        for m in pattern.finditer(text):
            expr = m.group("expr").rstrip(_TRAILING)
            if expr:
                phrases.append(_Phrase(m.start(), m.start("expr") + len(expr), expr, yields))
    for pattern in (_KEYWORD, _ISO):
        phrases.extend(_Phrase(m.start(), m.end(), m.group(), True) for m in pattern.finditer(text))
    return phrases


def _pick(phrases: list[_Phrase]) -> _Phrase | None:
    kept = [
        p
        for p in phrases
        if not (p.yields and any(q.end == p.end and q.start < p.start for q in phrases))
    ]
    return max(kept, key=lambda p: p.start, default=None)


def _resolve(
    expr: str, *, anchor: date, date_order: DateOrder, weekday_on_anchor: bool
) -> date | None:
    e = " ".join(expr.lower().split())
    monday = anchor - timedelta(days=anchor.weekday())
    if e in ("today", "eod", "end of day", "end of the day"):
        return anchor
    if e == "tomorrow":
        return anchor + timedelta(days=1)
    if e in ("eow", "end of week", "end of the week"):
        # Friday of this week; from Friday on, the following Friday.
        return monday + timedelta(days=4 if anchor.weekday() < 4 else 11)
    if e == "end of next week":
        return monday + timedelta(days=11)
    if e == "next week":
        return monday + timedelta(days=7)
    if e in ("eom", "end of month", "end of the month"):
        return anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    if m := _WEEKDAY_EXPR.match(e):
        qualifier, name = m.groups()
        weekday = _WEEKDAY_INDEX[name[:3]]
        if qualifier == "next":  # gap G6: that weekday in the following calendar week
            return monday + timedelta(days=7 + weekday)
        days = (weekday - anchor.weekday()) % 7
        return anchor + timedelta(days=days or (0 if weekday_on_anchor else 7))
    if _ISO_FULL.match(e):
        try:
            return date.fromisoformat(e)
        except ValueError:
            return None
    return _calendar_date(e, anchor=anchor, date_order=date_order)


def _calendar_date(e: str, *, anchor: date, date_order: DateOrder) -> date | None:
    """`12 Dec`, `03/04/2027`, `3/4`. Without a year: the first occurrence on or after anchor."""
    if not (_NUMERIC_DATE.search(e) or (_MONTH_WORD.search(e) and any(c.isdigit() for c in e))):
        return None
    try:
        import dateparser  # slow import; only needed for calendar dates

        parsed = dateparser.parse(
            e,
            settings={
                "RELATIVE_BASE": datetime.combine(anchor, time()),
                "PREFER_DATES_FROM": "future",
                "DATE_ORDER": date_order,
                "STRICT_PARSING": False,
                "RETURN_TIME_AS_PERIOD": False,
            },
        )
    except Exception:
        return None
    if parsed is None:
        return None
    if _HAS_YEAR.search(e):
        return parsed.date()
    # dateparser's "future" skips the anchor day itself; the spec wants on or after.
    for year in range(anchor.year, anchor.year + 9):  # 29 Feb may be up to 8 years away
        try:
            candidate = date(year, parsed.month, parsed.day)
        except ValueError:
            continue
        if candidate >= anchor:
            return candidate
    return None
