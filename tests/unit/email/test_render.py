from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from actiontrack.email.render import EmailItem, RenderedEmail, render_followup

TODAY = date(2026, 11, 25)
SIGN_OFF = "Thanks,\nMohit"
SNAPSHOTS = Path(__file__).parent / "snapshots"


def item(
    short_id: str,
    task: str,
    due: str | None,
    meeting_date: str = "2026-11-18",
    meeting_title: str | None = "Weekly sync",
) -> EmailItem:
    return EmailItem(
        short_id=short_id,
        task=task,
        due_date=date.fromisoformat(due) if due else None,
        meeting_title=meeting_title,
        meeting_date=date.fromisoformat(meeting_date),
    )


BUDGET = item("a1b2", "Send the budget draft", "2026-11-20", "2026-11-02", "Kickoff")
VENUE = item("c3d4", "Book the venue", "2026-11-10", "2026-11-04", None)
DOCS = item("e5f6", "Update the docs page", None)
REVIEW = item("0a1b", "Review the PR", "2026-12-01", "2026-11-11", "Planning")
RETRO = item("9f8e", "Share the retro notes", "2026-11-28", "2026-11-16", "Retro")


def render(
    overdue: list[EmailItem], open_: list[EmailItem], *, sign_off: str = SIGN_OFF
) -> RenderedEmail:
    return render_followup(
        first_name="Priya", overdue=overdue, open_=open_, today=TODAY, sign_off=sign_off
    )


def snapshot(name: str) -> str:
    return (SNAPSHOTS / name).read_bytes().decode("utf-8")


def mixed() -> RenderedEmail:
    return render([BUDGET, VENUE], [DOCS, REVIEW, RETRO])


def test_TC_M9_01_mixed_body_matches_snapshot() -> None:
    assert mixed().body == snapshot("mixed.txt")


def test_TC_M9_02_mixed_subject_counts_open_not_overdue() -> None:
    assert mixed().subject == "Follow-up: your open action items (3 open, 2 overdue)"


def test_TC_M9_03_open_only_has_no_overdue_section() -> None:
    email = render([], [DOCS, RETRO])
    assert email.body == snapshot("open_only.txt")
    assert "Overdue" not in email.body
    assert email.subject == "Follow-up: your open action items (2 open)"


def test_TC_M9_04_overdue_only_has_no_open_section() -> None:
    email = render([BUDGET, VENUE], [])
    assert email.body == snapshot("overdue_only.txt")
    assert "Open (" not in email.body
    assert email.subject == "Follow-up: your open action items (0 open, 2 overdue)"


def test_TC_M9_05_both_empty_raises() -> None:
    with pytest.raises(ValueError):
        render([], [])


def test_TC_M9_06_overdue_sorted_most_overdue_first() -> None:
    body = render([BUDGET, VENUE], []).body
    assert body.index("Book the venue") < body.index("Send the budget draft")
    assert "(due 2026-11-10, 15 days overdue) [c3d4]" in body
    assert "(due 2026-11-20, 5 days overdue) [a1b2]" in body


def test_TC_M9_06_same_due_date_sorted_by_short_id() -> None:
    later = item("ffff", "Second", "2026-11-20")
    earlier = item("0000", "First", "2026-11-20")
    body = render([later, earlier], [item("bbbb", "B", None), item("aaaa", "A", None)]).body
    assert body.index("[0000]") < body.index("[ffff]")
    assert body.index("[aaaa]") < body.index("[bbbb]")


def test_TC_M9_07_one_day_overdue_is_singular() -> None:
    body = render([item("a1b2", "Yesterday's task", "2026-11-24")], []).body
    assert "(due 2026-11-24, 1 day overdue) [a1b2]" in body


def test_TC_M9_08_dated_open_item_before_undated() -> None:
    body = render([], [DOCS, REVIEW]).body
    assert body.index("Review the PR") < body.index("Update the docs page")
    assert "- Update the docs page (no due date) [e5f6]\n" in body
    assert "- Review the PR (due 2026-12-01) [0a1b]\n" in body


def test_TC_M9_09_missing_meeting_title_falls_back_to_meeting() -> None:
    body = render([], [item("e5f6", "Untitled", None, "2026-11-18", None)]).body
    assert "  From: Meeting, 2026-11-18\n" in body


def test_TC_M9_10_rendering_is_deterministic() -> None:
    first, second = mixed(), mixed()
    assert first.subject.encode() == second.subject.encode()
    assert first.body.encode() == second.body.encode()


@pytest.mark.parametrize(
    "build",
    [mixed, lambda: render([], [DOCS]), lambda: render([VENUE], [])],
    ids=["mixed", "open_only", "overdue_only"],
)
def test_TC_M9_11_no_trailing_whitespace_single_final_newline(
    build: Callable[[], RenderedEmail],
) -> None:
    email = build()
    assert all(line == line.rstrip() for line in email.body.split("\n"))
    assert email.body.endswith("Mohit\n")
    assert not email.body.endswith("\n\n")
    assert "\r" not in email.body
    assert SIGN_OFF in email.body


def test_TC_M9_12_task_text_is_not_templated_or_escaped() -> None:
    task = "Fix {{ x }} and <b>bold</b> & {% if %}"
    body = render([], [item("e5f6", task, None)]).body
    assert f"- {task} (no due date) [e5f6]\n" in body


@pytest.mark.parametrize(
    "due", [None, "2026-11-25", "2026-11-26"], ids=["no_due", "due_today", "due_later"]
)
def test_TC_M9_13_overdue_item_must_be_due_before_today(due: str | None) -> None:
    with pytest.raises(ValueError):
        render([item("a1b2", "Not overdue", due)], [DOCS])


def test_TC_M9_14_trailing_spaces_in_inputs_are_stripped() -> None:
    body = render([], [item("e5f6", "Padded task  ", None)], sign_off="Thanks,  \nMohit \t").body
    assert "- Padded task   (no due date) [e5f6]\n" in body  # inner spaces are left alone
    assert body.endswith("\n\nThanks,\nMohit\n")
    assert all(line == line.rstrip() for line in body.split("\n"))


def test_jinja2_is_imported_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "actiontrack.email.render")
    monkeypatch.setitem(sys.modules, "jinja2", None)  # any import of it now fails
    importlib.import_module("actiontrack.email.render")
