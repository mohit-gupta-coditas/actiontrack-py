from __future__ import annotations

from datetime import date

import pytest

from actiontrack.models import Flag, LineWarning, ParsedItem, WarningCode
from actiontrack.parsing.items import (
    CheckboxLine,
    MalformedCheckbox,
    OwnerSplit,
    classify_line,
    clean_inline_markdown,
    extract_items,
    split_owner,
)
from tests.unit.parsing.conftest import NOTE_PATH, make_note, make_roster

PRIYA = "priya.shah@coditas.com"
RAHUL = "rahul.mehta@coditas.com"
FRI = date(2026, 11, 20)
MON = date(2026, 11, 23)
NO_FLAGS: frozenset[Flag] = frozenset()


def extract(
    *lines: str, roster: tuple[str, ...] = ()
) -> tuple[list[ParsedItem], list[LineWarning]]:
    return extract_items(make_note(*lines), make_roster(*roster))


def one(line: str, roster: tuple[str, ...] = ()) -> ParsedItem:
    """The single item extracted from one line, asserting there were no warnings."""
    items, warnings = extract(line, roster=roster)
    assert warnings == []
    assert len(items) == 1
    return items[0]


def warned(line: str) -> LineWarning:
    """The single warning from one line, asserting no item was produced."""
    items, warnings = extract(line)
    assert items == []
    assert len(warnings) == 1
    return warnings[0]


# --- checkbox detection ----------------------------------------------------------------------


def test_TC_M4_01_owner_task_and_due() -> None:
    item = one("- [ ] Priya to send the revised quote by Friday")
    assert item.owner.owner_key == PRIYA
    assert item.owner.owner_raw == "Priya"
    assert item.task == "send the revised quote"
    assert item.due.due_date == FRI
    assert item.due.due_raw == "by Friday"
    assert item.checked is False
    assert item.flags == NO_FLAGS
    assert item.raw_text == "- [ ] Priya to send the revised quote by Friday"
    assert item.note_path == NOTE_PATH
    assert item.line_no == 1
    assert item.meeting_date == date(2026, 11, 18)
    assert item.note_title == "Weekly sync"


def test_TC_M4_02_checked_item() -> None:
    item = one("- [x] Rahul to book venue")
    assert item.checked is True
    assert item.owner.owner_key == RAHUL
    assert item.task == "book venue"


def test_TC_M4_03_star_and_plus_bullets() -> None:
    items, warnings = extract("* [X] Rahul to book venue", "+ [ ] Priya to send quote")
    assert warnings == []
    assert [(i.checked, i.task) for i in items] == [(True, "book venue"), (False, "send quote")]


def test_TC_M4_04_indented_checkbox() -> None:
    item = one("    - [ ] Priya will check numbers")
    assert item.owner.owner_key == PRIYA
    assert item.task == "check numbers"
    assert item.flags == {Flag.NO_DUE}


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("-[ ] Rahul to call", id="TC_M4_05_no_space_after_bullet"),
        pytest.param("- [] Rahul to call", id="TC_M4_06_empty_brackets"),
        pytest.param("[ ] Rahul to call", id="TC_M4_07_no_bullet"),
        pytest.param("- [-] Rahul to call", id="TC_M4_08_unknown_marker"),
    ],
)
def test_malformed_checkbox(line: str) -> None:
    warning = warned(line)
    assert warning.code == WarningCode.MALFORMED_CHECKBOX
    assert warning.text == line
    # Reported on the line where it sits in the file.
    _, warnings = extract_items(make_note("text", line, first_line_no=7), make_roster())
    assert [w.line_no for w in warnings] == [8]


@pytest.mark.parametrize("line", ["- [ ]", "- [x]   ", "  * [ ] "])
def test_TC_M4_09_checkbox_without_text(line: str) -> None:
    warning = warned(line)
    assert warning.code == WarningCode.EMPTY_TASK
    assert warning.text == line.strip()


@pytest.mark.parametrize("fence", ["```", "~~~", "```markdown"])
def test_TC_M4_10_checkboxes_in_code_fences_are_ignored(fence: str) -> None:
    closing = "~~~" if fence == "~~~" else "```"
    items, warnings = extract(
        fence, "- [ ] Priya to send quote", "-[ ] broken", closing, "- [ ] Rahul to book venue"
    )
    assert warnings == []
    assert [i.task for i in items] == ["book venue"]
    assert items[0].line_no == 5


def test_TC_M4_23_brackets_mid_line_are_ordinary_text() -> None:
    assert extract("Some text mentioning [ ] brackets mid-line") == ([], [])
    assert classify_line("Some text mentioning [ ] brackets mid-line") is None


@pytest.mark.parametrize(
    "line, expected",
    [
        ("- [ ] task", CheckboxLine(False, "task")),
        ("  + [X] Done thing  ", CheckboxLine(True, "Done thing  ")),
        ("- [ ]", MalformedCheckbox(WarningCode.EMPTY_TASK)),
        ("*[x] x", MalformedCheckbox(WarningCode.MALFORMED_CHECKBOX)),
        ("- [o] x", MalformedCheckbox(WarningCode.MALFORMED_CHECKBOX)),
        ("- plain bullet", None),
        ("- [the deck](http://x) link", None),
        ("**Bold** text", None),
        ("", None),
    ],
)
def test_classify_line(line: str, expected: object) -> None:
    assert classify_line(line) == expected


# --- owner ---------------------------------------------------------------------------------


def test_TC_M4_11_full_name_and_colon() -> None:
    item = one("- [ ] Rahul Mehta: book venue")
    assert item.owner.owner_key == RAHUL
    assert item.owner.owner_raw == "Rahul Mehta"
    assert item.task == "book venue"


def test_TC_M4_12_em_dash_connector() -> None:
    item = one("- [ ] Priya — draft the proposal")
    assert item.owner.owner_key == PRIYA
    assert item.task == "draft the proposal"


def test_TC_M4_13_mention_anywhere() -> None:
    item = one("- [ ] Follow up with legal @rahul.mehta by Monday")
    assert item.owner.owner_key == RAHUL
    assert item.owner.owner_raw == "@rahul.mehta"
    assert item.task == "Follow up with legal"
    assert item.due.due_date == MON
    assert item.flags == NO_FLAGS


def test_TC_M4_14_lowercase_start_has_no_owner() -> None:
    item = one("- [ ] send the deck to Rahul")
    assert item.owner.owner_key is None
    assert item.owner.owner_raw is None
    assert item.task == "send the deck to Rahul"
    assert Flag.UNASSIGNED in item.flags


def test_TC_M4_15_no_owner_no_due() -> None:
    item = one("- [ ] Update the onboarding doc")
    assert item.task == "Update the onboarding doc"
    assert item.flags == {Flag.UNASSIGNED, Flag.NO_DUE}


def test_TC_M4_16_two_owners_with_and() -> None:
    item = one("- [ ] Priya and Rahul to review contract EOW")
    assert item.owner.owner_key == PRIYA
    assert item.task == "review contract"
    assert item.due.due_date == FRI
    assert item.flags == {Flag.MULTI_OWNER}


@pytest.mark.parametrize("line", ["- [ ] Priya, Rahul to sync", "- [ ] Priya & Rahul to sync"])
def test_TC_M4_17_two_owners_with_comma_or_ampersand(line: str) -> None:
    item = one(line)
    assert item.owner.owner_key == PRIYA
    assert item.task == "sync"
    assert Flag.MULTI_OWNER in item.flags


def test_TC_M4_20_ambiguous_first_name() -> None:
    item = one("- [ ] Priya to send quote", roster=("Priya Shah", "Priya Nair"))
    assert item.owner.owner_key is None
    assert len(item.owner.candidates) == 2
    assert Flag.AMBIGUOUS_OWNER in item.flags


def test_label_before_owner_is_skipped() -> None:
    item = one("  - [ ] Sub-task: Priya will check numbers")
    assert item.owner.owner_key == PRIYA
    assert item.task == "check numbers"


@pytest.mark.parametrize(
    "body, expected",
    [
        ("Priya to send quote", OwnerSplit("Priya", "send quote", False)),
        ("Priya - draft it", OwnerSplit("Priya", "draft it", False)),
        ("Priya \u2013 draft it", OwnerSplit("Priya", "draft it", False)),
        ("Priya should call", OwnerSplit("Priya", "call", False)),
        ("Priya must call", OwnerSplit("Priya", "call", False)),
        ("Priya needs to call", OwnerSplit("Priya", "call", False)),
        ("Priya is to call", OwnerSplit("Priya", "call", False)),
        ("Rahul to call Priya to confirm", OwnerSplit("Rahul", "call Priya to confirm", False)),
        ("@priya to call", OwnerSplit("@priya", "call", False)),
        ("Anna Maria Lopez will call", OwnerSplit("Anna Maria Lopez", "call", False)),
        ("Priya and the team to call", OwnerSplit(None, "Priya and the team to call", False)),
        ("Rahul Mehta: Priya's deck", OwnerSplit("Rahul Mehta", "Priya's deck", False)),
        ("Ping @rahul.mehta.", OwnerSplit("@rahul.mehta", "Ping .", False)),
        ("mail priya@coditas.com", OwnerSplit(None, "mail priya@coditas.com", False)),
        ("Priya to", OwnerSplit(None, "Priya to", False)),
    ],
)
def test_split_owner(body: str, expected: OwnerSplit) -> None:
    assert split_owner(body) == expected


def test_split_owner_long_owner_list_does_not_backtrack() -> None:
    # Took exponential time when a name could also swallow `and`.
    assert split_owner(" and ".join(["Ab"] * 200) + " x").owner_raw is None


# --- task and due --------------------------------------------------------------------------


def test_TC_M4_18_inline_markdown_is_cleaned() -> None:
    item = one("- [ ] **Priya** to send [the deck](http://x) by Friday.")
    assert item.owner.owner_key == PRIYA
    assert item.task == "send the deck"
    assert item.due.due_date == FRI
    assert item.raw_text == "- [ ] **Priya** to send [the deck](http://x) by Friday."


def test_TC_M4_19_nothing_left_but_the_due_phrase() -> None:
    warning = warned("- [ ] Priya to by Friday")
    assert warning.code == WarningCode.EMPTY_TASK
    assert warning.line_no == 1


def test_TC_M4_21_unparsed_due_is_kept_out_of_the_task() -> None:
    item = one("- [ ] Rahul to fix it ASAP")
    assert item.task == "fix it"
    assert item.due.due_raw == "ASAP"
    assert item.due.due_date is None
    assert item.flags == {Flag.UNPARSED_DUE}


def test_due_in_brackets_leaves_no_empty_brackets() -> None:
    item = one("- [x] **Rahul Mehta**: book venue (due 2026-12-01)")
    assert item.owner.owner_key == RAHUL
    assert item.task == "book venue"
    assert item.due.due_raw == "due 2026-12-01"
    assert item.due.due_date == date(2026, 12, 1)
    assert item.checked is True


def test_task_keeps_casing_and_trims_punctuation() -> None:
    assert one("- [ ] Priya: Ship the API v2 — by Friday;").task == "Ship the API v2"


def test_date_order_is_passed_to_due_parsing() -> None:
    note = make_note("- [ ] Priya to renew by 03/04/2027")
    (dmy,), _ = extract_items(note, make_roster())
    (mdy,), _ = extract_items(note, make_roster(), date_order="MDY")
    assert dmy.due.due_date == date(2027, 4, 3)
    assert mdy.due.due_date == date(2027, 3, 4)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("**Priya** to send", "Priya to send"),
        ("__Priya__ to _send_ it", "Priya to send it"),
        ("*send*  the   `deck`", "send the deck"),
        ("see [the deck](http://x/a_b) now", "see the deck now"),
        ("ping @rahul_mehta about snake_case", "ping @rahul_mehta about snake_case"),
    ],
)
def test_clean_inline_markdown(text: str, expected: str) -> None:
    assert clean_inline_markdown(text) == expected


# --- whole note ----------------------------------------------------------------------------


def test_TC_M4_22_items_and_warnings_in_line_order() -> None:
    note = make_note(
        "## Action items",
        "- [ ] Priya to send quote by Friday",
        "-[ ] Rahul to call",
        "- [x] Rahul to book venue",
        "Some discussion.",
        "  - [ ] Priya will check numbers",
        "- [~] Rahul to chase",
        "- [ ] Update the onboarding doc",
        "* [ ] Rahul to share notes EOD",
        first_line_no=10,
    )
    items, warnings = extract_items(note, make_roster())
    assert [(i.line_no, i.task) for i in items] == [
        (11, "send quote"),
        (13, "book venue"),
        (15, "check numbers"),
        (17, "Update the onboarding doc"),
        (18, "share notes"),
    ]
    assert [(w.line_no, w.code) for w in warnings] == [
        (12, WarningCode.MALFORMED_CHECKBOX),
        (16, WarningCode.MALFORMED_CHECKBOX),
    ]
    assert all(w.path == NOTE_PATH for w in warnings)
