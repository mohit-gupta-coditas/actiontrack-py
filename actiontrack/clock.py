"""Injectable source of "today" and "now" (REQ-CLI-10)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Protocol

from actiontrack.errors import UserInputError

TODAY_ENV = "ACTIONTRACK_TODAY"
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Clock(Protocol):
    def today(self) -> date: ...

    def now(self) -> datetime:
        """Timezone-aware, in the local timezone."""
        ...


class SystemClock:
    def today(self) -> date:
        return self.now().date()

    def now(self) -> datetime:
        return datetime.now().astimezone()


class FixedClock:
    """A clock frozen at a given day. `now` defaults to the start of that day, local time."""

    def __init__(self, today: date, now: datetime | None = None) -> None:
        self._today = today
        self._now = now if now is not None else datetime.combine(today, time()).astimezone()

    def today(self) -> date:
        return self._today

    def now(self) -> datetime:
        return self._now


def clock_from_env(env: Mapping[str, str]) -> Clock:
    """`ACTIONTRACK_TODAY=YYYY-MM-DD` pins the clock; otherwise the system clock is used."""
    raw = env.get(TODAY_ENV, "").strip()
    if not raw:
        return SystemClock()
    if not _ISO_DATE.fullmatch(raw):
        raise UserInputError(
            f"invalid {TODAY_ENV} value {raw!r}", hint="use the format YYYY-MM-DD, e.g. 2026-11-18"
        )
    try:
        return FixedClock(date.fromisoformat(raw))
    except ValueError as e:
        raise UserInputError(f"invalid {TODAY_ENV} value {raw!r}: {e}") from e
