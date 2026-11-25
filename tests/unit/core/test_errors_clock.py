from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from actiontrack.clock import FixedClock, SystemClock, clock_from_env
from actiontrack.errors import (
    ActionTrackError,
    ExitCode,
    ExternalServiceError,
    FatalError,
    ForbiddenToolError,
    UserInputError,
)


def test_exit_codes_per_error_type() -> None:
    assert FatalError.exit_code == ExitCode.FATAL == 1
    assert UserInputError.exit_code == ExitCode.USER == 2
    assert ExternalServiceError.exit_code == ExitCode.EXTERNAL == 3
    assert ForbiddenToolError.exit_code == ExitCode.FATAL
    assert ExitCode.INTERRUPTED == 130


def test_error_carries_message_and_hint() -> None:
    e = UserInputError("bad", hint="try x")
    assert isinstance(e, ActionTrackError)
    assert (e.message, e.hint, str(e)) == ("bad", "try x", "bad")
    assert FatalError("boom").hint is None


def test_TC_M0_17_actiontrack_today_pins_clock() -> None:
    clock = clock_from_env({"ACTIONTRACK_TODAY": "2026-11-18"})
    assert isinstance(clock, FixedClock)
    assert clock.today() == date(2026, 11, 18)
    assert clock.now().date() == date(2026, 11, 18)
    assert clock.now().tzinfo is not None


@pytest.mark.parametrize("raw", ["18th-ish", "2026-13-01", "20261118"])
def test_TC_M0_18_invalid_actiontrack_today(raw: str) -> None:
    with pytest.raises(UserInputError, match="ACTIONTRACK_TODAY"):
        clock_from_env({"ACTIONTRACK_TODAY": raw})


def test_no_env_gives_system_clock() -> None:
    clock = clock_from_env({})
    assert isinstance(clock, SystemClock)
    now = clock.now()
    assert now.tzinfo is not None
    assert clock.today() in (now.date(), datetime.now().astimezone().date())


def test_fixed_clock_explicit_now() -> None:
    now = datetime(2026, 11, 18, 15, 30, tzinfo=UTC)
    assert FixedClock(date(2026, 11, 18), now).now() == now
