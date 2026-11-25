from __future__ import annotations

from datetime import date
from typing import Literal

import pytest

from actiontrack.errors import UserInputError
from actiontrack.models import DueResolution, Flag
from actiontrack.parsing.dates import extract_due, parse_user_date, resolve_expr

WED = date(2026, 11, 18)
FRI = date(2026, 11, 20)
SAT = date(2026, 11, 21)
NO_FLAGS: frozenset[Flag] = frozenset()


def due(text: str, anchor: date = WED, order: Literal["DMY", "MDY"] = "DMY") -> DueResolution:
    return extract_due(text, anchor=anchor, date_order=order)


def assert_due(res: DueResolution, due_date: date | None, due_raw: str | None) -> None:
    assert res.due_date == due_date
    assert res.due_raw == due_raw
    assert res.flags == NO_FLAGS


# --- extract_due: resolved phrases ----------------------------------------------------------


RESOLVED = [
    # (TC, text, anchor, date_order, due_date, due_raw)
    ("TC_M3_01", "send the revised quote by Friday", WED, "DMY", date(2026, 11, 20), "by Friday"),
    ("TC_M3_02", "send quote by Friday", FRI, "DMY", date(2026, 11, 27), "by Friday"),
    ("TC_M3_03", "send quote by Monday", WED, "DMY", date(2026, 11, 23), "by Monday"),
    ("TC_M3_04", "send quote by next Friday", WED, "DMY", date(2026, 11, 27), "by next Friday"),
    ("TC_M3_05", "deck EOD", WED, "DMY", WED, "EOD"),
    ("TC_M3_06", "deck EOW", WED, "DMY", date(2026, 11, 20), "EOW"),
    ("TC_M3_07", "deck EOW", SAT, "DMY", date(2026, 11, 27), "EOW"),
    ("TC_M3_08", "deck by next week", WED, "DMY", date(2026, 11, 23), "by next week"),
    ("TC_M3_09", "deck by end of month", WED, "DMY", date(2026, 11, 30), "by end of month"),
    ("TC_M3_10", "deck by end of next week", WED, "DMY", date(2026, 11, 27), "by end of next week"),
    ("TC_M3_11", "deck by tomorrow", WED, "DMY", date(2026, 11, 19), "by tomorrow"),
    ("TC_M3_12", "renew licence by 5 Jan", date(2026, 12, 16), "DMY", date(2027, 1, 5), "by 5 Jan"),
    ("TC_M3_13", "renew by 12 Dec", WED, "DMY", date(2026, 12, 12), "by 12 Dec"),
    # Anchored after the date: an ISO date is never moved.
    (
        "TC_M3_14",
        "renew due 2026-12-01",
        date(2027, 6, 1),
        "DMY",
        date(2026, 12, 1),
        "due 2026-12-01",
    ),
    ("TC_M3_15", "renew by 03/04/2027", WED, "DMY", date(2027, 4, 3), "by 03/04/2027"),
    ("TC_M3_16", "renew by 03/04/2027", WED, "MDY", date(2027, 3, 4), "by 03/04/2027"),
    ("TC_M3_18", "review on 3 Dec", WED, "DMY", date(2026, 12, 3), "on 3 Dec"),
    ("TC_M3_22", "draft by Monday, review by Friday", WED, "DMY", date(2026, 11, 20), "by Friday"),
    ("TC_M3_23", "send quote by Friday.", WED, "DMY", date(2026, 11, 20), "by Friday"),
]


@pytest.mark.parametrize(
    ("text", "anchor", "order", "expected", "raw"),
    [pytest.param(*row[1:], id=row[0]) for row in RESOLVED],
)
def test_extract_due_resolves(
    text: str, anchor: date, order: Literal["DMY", "MDY"], expected: date, raw: str
) -> None:
    res = due(text, anchor, order)
    assert_due(res, expected, raw)
    assert res.span is not None
    assert text[res.span[0] : res.span[1]] == raw


# --- extract_due: flags ---------------------------------------------------------------------


def test_TC_M3_17_on_without_date_is_not_a_due_phrase() -> None:
    res = due("work on the deck")
    assert res == DueResolution(None, None, frozenset({Flag.NO_DUE}), None)


def test_TC_M3_19_asap_is_unparsed() -> None:
    res = due("fix it ASAP")
    assert res.due_date is None
    assert res.due_raw == "ASAP"
    assert res.flags == frozenset({Flag.UNPARSED_DUE})
    assert res.span == (7, 11)


def test_TC_M3_20_unresolvable_phrase_keeps_span() -> None:
    text = "ship by the blue moon"
    res = due(text)
    assert res.due_date is None
    assert res.due_raw == "by the blue moon"
    assert res.flags == frozenset({Flag.UNPARSED_DUE})
    assert res.span is not None
    assert text[res.span[0] : res.span[1]] == "by the blue moon"


def test_TC_M3_21_no_phrase() -> None:
    assert due("send quote") == DueResolution(None, None, frozenset({Flag.NO_DUE}), None)


def test_TC_M3_26_span_matches_phrase() -> None:
    text = "send quote by Friday"
    res = due(text)
    assert res.span == (11, 20)
    assert text[res.span[0] : res.span[1]] == "by Friday"


# --- extract_due: detection details ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "raw"),
    [
        ("Send deck eow", date(2026, 11, 20), "eow"),
        ("ship 2026-12-01", date(2026, 12, 1), "2026-12-01"),
        ("deck due by Friday", date(2026, 11, 20), "due by Friday"),
        ("deck due on 3 Dec", date(2026, 12, 3), "due on 3 Dec"),
        ("deck before Monday", date(2026, 11, 23), "before Monday"),
        ("deck no later than 12 Dec", date(2026, 12, 12), "no later than 12 Dec"),
        ("deck deadline: Friday", date(2026, 11, 20), "deadline: Friday"),
        ("deck by Friday (if possible)", date(2026, 11, 20), "by Friday"),
        ("deck by Friday; then review", date(2026, 11, 20), "by Friday"),
        ("deck by Friday - priority", date(2026, 11, 20), "by Friday"),
        ("deck by Friday!", date(2026, 11, 20), "by Friday"),
        ("deck send end of the week", date(2026, 11, 20), "end of the week"),
        ("present on Friday", date(2026, 11, 20), "on Friday"),
        ("follow up on Monday's notes by Friday", date(2026, 11, 20), "by Friday"),
        ("draft by Monday then ship tomorrow", None, None),
    ],
)
def test_detection_variants(text: str, expected: date | None, raw: str | None) -> None:
    res = due(text)
    if raw is None:
        # The connector expression runs to the end of the text: one unresolvable phrase.
        assert res.flags == frozenset({Flag.UNPARSED_DUE})
        assert res.due_raw == "by Monday then ship tomorrow"
        return
    assert_due(res, expected, raw)


def test_on_followed_by_word_starting_with_month_letters_is_ignored() -> None:
    assert due("focus on monitoring").flags == frozenset({Flag.NO_DUE})
    assert due("call on Decision log").flags == frozenset({Flag.NO_DUE})


# --- resolve_expr ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "anchor", "expected"),
    [
        ("today", WED, WED),
        ("End of the day", WED, WED),
        ("this friday", WED, date(2026, 11, 20)),
        ("thu", WED, date(2026, 11, 19)),
        ("wednesday", WED, date(2026, 11, 25)),
        ("next monday", date(2026, 11, 22), date(2026, 11, 23)),
        ("next wednesday", WED, date(2026, 11, 25)),
        ("end of week", FRI, date(2026, 11, 27)),
        ("end of next week", SAT, date(2026, 11, 27)),
        ("end of next week", date(2026, 11, 23), date(2026, 12, 4)),
        ("EOM", date(2026, 12, 3), date(2026, 12, 31)),
        ("end of the month", date(2028, 2, 10), date(2028, 2, 29)),
        ("18 Nov", WED, WED),
        ("17 Nov", WED, date(2027, 11, 17)),
        ("Dec 12", WED, date(2026, 12, 12)),
        ("12th December", WED, date(2026, 12, 12)),
        ("12 Dec 2025", WED, date(2025, 12, 12)),
        ("3/4", WED, date(2027, 4, 3)),
        ("29 Feb", WED, date(2028, 2, 29)),
        ("2026-12-01", WED, date(2026, 12, 1)),
        ("2026-13-45", WED, None),
        ("ASAP", WED, None),
        ("the blue moon", WED, None),
        ("12", WED, None),
        ("", WED, None),
    ],
)
def test_resolve_expr(expr: str, anchor: date, expected: date | None) -> None:
    assert resolve_expr(expr, anchor=anchor) == expected


def test_resolve_expr_numeric_without_year_follows_date_order() -> None:
    assert resolve_expr("3/4", anchor=WED, date_order="MDY") == date(2027, 3, 4)
    assert resolve_expr("12/12", anchor=WED, date_order="MDY") == date(2026, 12, 12)


# --- parse_user_date ------------------------------------------------------------------------


def test_TC_M3_24_user_weekday_is_on_or_after_today() -> None:
    assert parse_user_date("friday", today=FRI) == FRI
    assert parse_user_date("monday", today=FRI) == date(2026, 11, 23)
    assert parse_user_date("2026-12-31", today=FRI) == date(2026, 12, 31)
    assert parse_user_date(" tomorrow ", today=FRI) == date(2026, 11, 21)


def test_TC_M3_25_user_date_nonsense_raises() -> None:
    with pytest.raises(UserInputError) as exc:
        parse_user_date("nonsense", today=FRI)
    assert exc.value.message == 'could not understand date "nonsense"'
    assert exc.value.hint == "use YYYY-MM-DD"
