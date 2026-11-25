from __future__ import annotations

import hashlib
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from actiontrack.models import NoteMeta, SkipReason, SkipRecord
from actiontrack.parsing.note_loader import load_note, parse_meeting_date

FIXTURES = Path(__file__).parents[2] / "fixtures" / "notes" / "loader"

VALID_NOTE = (
    "---\n"
    "date: 2026-11-18\n"
    "title: Q4 pricing sync\n"
    "attendees: [Priya Shah, Rahul Mehta]\n"
    "---\n"
    "## Notes\n"
    "- [ ] Priya to send the quote\n"
)


def load_ok(path: Path, **kwargs: object) -> NoteMeta:
    result = load_note(path, **kwargs)  # type: ignore[arg-type]
    assert isinstance(result, NoteMeta), result
    return result


def load_skip(path: Path, reason: SkipReason) -> SkipRecord:
    result = load_note(path)
    assert isinstance(result, SkipRecord), result
    assert result.reason == reason, result
    assert result.path == path
    return result


def write(tmp_path: Path, data: bytes | str, name: str = "note.md") -> Path:
    path = tmp_path / name
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    return path


# --- Layouts, date and attendee sources -------------------------------------------------------


def test_TC_M1_01_frontmatter_note() -> None:
    meta = load_ok(FIXTURES / "frontmatter_valid.md")
    assert meta.meeting_date == date(2026, 11, 18)
    assert meta.title == "Q4 pricing sync"
    assert meta.attendees_raw == (
        "Priya Shah <priya.shah@coditas.com>",
        "Priya Nair",
        "Rahul Mehta",
    )
    assert meta.lines[0] == (9, "## Notes")
    assert meta.lines[-1] == (12, "- [x] Rahul to book the venue")


def test_TC_M1_02_heading_layout_with_inline_attendees() -> None:
    meta = load_ok(FIXTURES / "heading_layout.md")
    assert meta.meeting_date == date(2026, 11, 18)
    assert meta.title == "Q4 pricing sync"
    assert meta.attendees_raw == ("Priya Shah", "Priya Nair", "Rahul Mehta")
    assert meta.lines[0] == (1, "# Q4 pricing sync — 2026-11-18")


def test_TC_M1_03_bold_date_line_without_frontmatter() -> None:
    meta = load_ok(FIXTURES / "bold_date_line.md")
    assert meta.meeting_date == date(2026, 11, 18)
    assert meta.title == "Weekly sync"
    assert meta.attendees_raw == ("Priya Shah", "Rahul Mehta")


def test_TC_M1_04_attendees_heading_with_bullets() -> None:
    meta = load_ok(FIXTURES / "attendees_heading.md")
    assert meta.attendees_raw == ("Priya Shah", "Rahul Mehta", "Anita Rao")
    assert meta.title == "Design review"


def test_TC_M1_05_slash_date_dmy() -> None:
    assert load_ok(FIXTURES / "slash_date.md").meeting_date == date(2026, 4, 3)


def test_TC_M1_06_slash_date_mdy() -> None:
    meta = load_ok(FIXTURES / "slash_date.md", date_order="MDY")
    assert meta.meeting_date == date(2026, 3, 4)


def test_TC_M1_07_no_date_anywhere() -> None:
    load_skip(FIXTURES / "no_date.md", SkipReason.MISSING_DATE)


def test_TC_M1_08_vague_date_is_unparseable() -> None:
    skip = load_skip(FIXTURES / "vague_date.md", SkipReason.UNPARSEABLE_DATE)
    assert "sometime next week" in skip.detail


def test_TC_M1_09_date_without_year_is_unparseable() -> None:
    skip = load_skip(FIXTURES / "date_no_year.md", SkipReason.UNPARSEABLE_DATE)
    assert "18 Nov" in skip.detail


def test_TC_M1_10_no_attendees_in_any_form() -> None:
    load_skip(FIXTURES / "no_attendees.md", SkipReason.MISSING_ATTENDEES)


def test_TC_M1_11_empty_attendees_list() -> None:
    load_skip(FIXTURES / "empty_attendees.md", SkipReason.MISSING_ATTENDEES)


# --- Frontmatter --------------------------------------------------------------------------------


def test_TC_M1_12_unclosed_frontmatter() -> None:
    load_skip(FIXTURES / "unclosed_frontmatter.md", SkipReason.INVALID_FRONTMATTER)


def test_TC_M1_13_yaml_error_reports_file_line() -> None:
    skip = load_skip(FIXTURES / "yaml_error.md", SkipReason.INVALID_FRONTMATTER)
    assert skip.line_no == 4


def test_TC_M1_14_frontmatter_not_a_mapping() -> None:
    skip = load_skip(FIXTURES / "frontmatter_list.md", SkipReason.INVALID_FRONTMATTER)
    assert "list" in skip.detail


# --- Bytes: empty, binary, encoding, BOM, line endings ------------------------------------------


@pytest.mark.parametrize(
    "data", [b"", b"  \n\t\r\n  ", b"\xef\xbb\xbf\n"], ids=["0-byte", "ws", "bom"]
)
def test_TC_M1_15_empty_and_whitespace_files(tmp_path: Path, data: bytes) -> None:
    load_skip(write(tmp_path, data), SkipReason.EMPTY_FILE)


def test_TC_M1_16_binary_file(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    load_skip(write(tmp_path, png, "image.md"), SkipReason.BINARY_FILE)


@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"], ids=["plain", "bom"])
def test_TC_M1_17_latin1_bytes(tmp_path: Path, bom: bytes) -> None:
    data = bom + b"# Caf\xe9 sync 2026-11-18\n"
    skip = load_skip(write(tmp_path, data), SkipReason.INVALID_ENCODING)
    assert f"offset {len(bom) + 5}" in skip.detail  # byte offset of 0xE9 in the file


def test_TC_M1_18_utf8_bom(tmp_path: Path) -> None:
    meta = load_ok(write(tmp_path, b"\xef\xbb\xbf" + VALID_NOTE.encode()))
    assert meta.meeting_date == date(2026, 11, 18)
    assert meta.attendees_raw == ("Priya Shah", "Rahul Mehta")
    assert meta.lines[0] == (6, "## Notes")


@pytest.mark.parametrize("eol", ["\r\n", "\r"], ids=["crlf", "cr"])
def test_TC_M1_19_crlf_and_cr_line_endings(tmp_path: Path, eol: str) -> None:
    meta = load_ok(write(tmp_path, VALID_NOTE.replace("\n", eol)))
    assert meta.title == "Q4 pricing sync"
    assert meta.lines == ((6, "## Notes"), (7, "- [ ] Priya to send the quote"))
    assert not any("\r" in text for _, text in meta.lines)


# --- Line numbers, read-only, errors --------------------------------------------------------


def test_TC_M1_20_body_keeps_file_line_numbers() -> None:
    meta = load_ok(FIXTURES / "line_numbers.md")
    assert (12, "- [ ] Priya to send the quote") in meta.lines
    assert meta.lines[0] == (8, "## Notes")


def test_TC_M1_21_horizontal_rule_is_not_frontmatter() -> None:
    meta = load_ok(FIXTURES / "hr_in_body.md")
    assert meta.title == "Retro"
    assert meta.attendees_raw == ("Priya Shah", "Rahul Mehta")
    assert (4, "---") in meta.lines


def test_TC_M1_22_hash_stable_and_file_untouched() -> None:
    path = FIXTURES / "frontmatter_valid.md"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    first, second = load_ok(path), load_ok(path)
    assert first.sha256 == second.sha256 == hashlib.sha256(before[0]).hexdigest()
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_TC_M1_23_directory_is_read_error(tmp_path: Path) -> None:
    skip = load_skip(tmp_path, SkipReason.READ_ERROR)
    assert skip.detail


def test_TC_M1_23_permission_error_is_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, VALID_NOTE)

    def deny(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", deny)
    skip = load_skip(path, SkipReason.READ_ERROR)
    assert "Permission denied" in skip.detail


@pytest.mark.slow
def test_TC_M1_24_large_note_is_fast(tmp_path: Path) -> None:
    body = "".join(
        f"- [ ] Person{i} to do task {i} by Friday\n" if i % 3 == 0 else f"Discussion line {i}\n"
        for i in range(20_000)
    )
    path = write(tmp_path, VALID_NOTE + body)
    start = time.perf_counter()
    meta = load_ok(path)
    assert time.perf_counter() - start < 1.0
    assert len(meta.lines) == 20_002


# --- parse_meeting_date and other spec edge cases -----------------------------------------------


@pytest.mark.parametrize(
    ("text", "order", "expected"),
    [
        ("2026-11-18", "DMY", date(2026, 11, 18)),
        ("Sync 2026-11-18 notes", "MDY", date(2026, 11, 18)),
        ("2026-13-45", "DMY", None),
        ("18 Nov 2026", "DMY", date(2026, 11, 18)),
        ("November 18, 2026", "DMY", date(2026, 11, 18)),
        ("03/04/2026", "DMY", date(2026, 4, 3)),
        ("03/04/2026", "MDY", date(2026, 3, 4)),
        ("Nov 2026", "DMY", None),
        ("18 Nov", "DMY", None),
        ("tomorrow", "DMY", None),
        ("in 2 days", "DMY", None),
        ("", "DMY", None),
    ],
)
def test_parse_meeting_date(text: str, order: str, expected: date | None) -> None:
    assert parse_meeting_date(text, date_order=order) == expected  # type: ignore[arg-type]


def test_parse_meeting_date_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import dateparser

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(dateparser, "parse", boom)
    assert parse_meeting_date("18 Nov 2026", date_order="DMY") is None


def test_dateparser_imported_lazily(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "dateparser", raising=False)
    load_ok(write(tmp_path, VALID_NOTE))
    assert "dateparser" not in sys.modules


def test_frontmatter_datetime_and_quoted_string(tmp_path: Path) -> None:
    dt = VALID_NOTE.replace("date: 2026-11-18", "date: 2026-11-18 10:30:00")
    assert load_ok(write(tmp_path, dt, "a.md")).meeting_date == date(2026, 11, 18)
    quoted = VALID_NOTE.replace("date: 2026-11-18", 'date: "18 Nov 2026"')
    assert load_ok(write(tmp_path, quoted, "b.md")).meeting_date == date(2026, 11, 18)


def test_frontmatter_invalid_calendar_date(tmp_path: Path) -> None:
    bad = VALID_NOTE.replace("date: 2026-11-18", "date: 2026-13-45")
    load_skip(write(tmp_path, bad), SkipReason.INVALID_FRONTMATTER)


def test_frontmatter_empty_date_is_missing(tmp_path: Path) -> None:
    load_skip(write(tmp_path, VALID_NOTE.replace("2026-11-18", "")), SkipReason.MISSING_DATE)


def test_frontmatter_empty_date_falls_back_to_body(tmp_path: Path) -> None:
    note = VALID_NOTE.replace("date: 2026-11-18", "date:") + "# Sync 2026-11-20\n"
    assert load_ok(write(tmp_path, note)).meeting_date == date(2026, 11, 20)


def test_frontmatter_attendees_string_is_split(tmp_path: Path) -> None:
    note = VALID_NOTE.replace("[Priya Shah, Rahul Mehta]", '"Priya Shah, Rahul; ,Anita "')
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya Shah", "Rahul", "Anita")


def test_frontmatter_participants_key(tmp_path: Path) -> None:
    note = VALID_NOTE.replace("attendees:", "participants:")
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya Shah", "Rahul Mehta")


def test_frontmatter_attendees_scalar_and_nested_values(tmp_path: Path) -> None:
    note = VALID_NOTE.replace("[Priya Shah, Rahul Mehta]", "[Priya, null, {a: b}, 42]")
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya", "42")
    single = VALID_NOTE.replace("[Priya Shah, Rahul Mehta]", "7")
    assert load_ok(write(tmp_path, single, "b.md")).attendees_raw == ("7",)


def test_empty_frontmatter_block_uses_body(tmp_path: Path) -> None:
    note = "---\n---\n# Sync — 2026-11-18\nAttendees: Priya\n"
    meta = load_ok(write(tmp_path, note))
    assert (meta.title, meta.attendees_raw) == ("Sync", ("Priya",))
    assert meta.lines[0][0] == 3


def test_frontmatter_closed_with_dots(tmp_path: Path) -> None:
    note = VALID_NOTE.replace("---\n## Notes", "...\n## Notes", 1)
    assert load_ok(write(tmp_path, note)).lines[0] == (6, "## Notes")


def test_date_line_after_first_checkbox_is_ignored(tmp_path: Path) -> None:
    note = "# Sync\nAttendees: Priya\n- [ ] Priya to do it\nDate: 2026-11-18\n"
    load_skip(write(tmp_path, note), SkipReason.MISSING_DATE)


def test_date_line_wins_over_h1(tmp_path: Path) -> None:
    note = "# Sync 2026-11-01\nDate: 2026-11-18\nAttendees: Priya\n"
    meta = load_ok(write(tmp_path, note))
    assert (meta.meeting_date, meta.title) == (date(2026, 11, 18), "Sync")


def test_h1_without_year_is_unparseable(tmp_path: Path) -> None:
    skip = load_skip(
        write(tmp_path, "# Sync — 18 Nov\nAttendees: Priya\n"), SkipReason.UNPARSEABLE_DATE
    )
    assert "18 Nov" in skip.detail


@pytest.mark.parametrize(
    ("h1", "title"),
    [
        ("# 2026-11-18 | Board meeting", "Board meeting"),
        ("# Sync: 18th November 2026 - follow-up", "Sync follow-up"),
        ("# Nov 18, 2026: Kickoff", "Kickoff"),
        ("# Kickoff", "Kickoff"),
        ("# 2026-11-18", None),
    ],
)
def test_title_from_h1(tmp_path: Path, h1: str, title: str | None) -> None:
    note = f"{h1}\nDate: 2026-11-18\nAttendees: Priya\n"
    assert load_ok(write(tmp_path, note)).title == title


@pytest.mark.parametrize(
    ("h1", "title"),
    [
        ("# Meeting: QA sync", "QA sync"),
        ("# notes: Retro — 2026-11-18", "Retro"),
        ("# Meeting:", None),
        ("# Meetings recap", "Meetings recap"),
    ],
)
def test_TC_M1_25_h1_title_drops_meeting_label(tmp_path: Path, h1: str, title: str | None) -> None:
    note = f"{h1}\nDate: 2026-11-18\nAttendees: Priya\n"
    assert load_ok(write(tmp_path, note)).title == title


def test_TC_M1_25_frontmatter_title_keeps_label(tmp_path: Path) -> None:
    note = "---\ntitle: 'Meeting: X'\ndate: 2026-11-18\nattendees: [Priya]\n---\n"
    assert load_ok(write(tmp_path, note)).title == "Meeting: X"


def test_inline_attendees_win_over_heading_list(tmp_path: Path) -> None:
    note = "# Sync 2026-11-18\n## Attendees\n- Anita\n\nAttendees: Priya, Rahul\n"
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya", "Rahul")


def test_attendees_heading_list_stops_at_blank_or_heading(tmp_path: Path) -> None:
    note = "# Sync 2026-11-18\n## Participants\n- Priya\n- Rahul\n\n- Not an attendee\n"
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya", "Rahul")
    note = "# Sync 2026-11-18\n## Attendees\n- Priya\n## Notes\n- Not an attendee\n"
    assert load_ok(write(tmp_path, note, "b.md")).attendees_raw == ("Priya",)


def test_attendees_heading_without_bullets(tmp_path: Path) -> None:
    note = "# Sync 2026-11-18\n## Attendees\nTBD\n- Not an attendee\n"
    load_skip(write(tmp_path, note), SkipReason.MISSING_ATTENDEES)


def test_empty_inline_attendees_line_is_ignored(tmp_path: Path) -> None:
    note = "# Sync 2026-11-18\n**Attendees:**\n## Attendees\n- Priya\n"
    assert load_ok(write(tmp_path, note)).attendees_raw == ("Priya",)


def test_binary_sniff_only_checks_first_8k(tmp_path: Path) -> None:
    data = (VALID_NOTE + "x" * 9000 + "\n").encode() + b"\x00"
    assert isinstance(load_note(write(tmp_path, data)), NoteMeta)


def test_lines_without_trailing_newline(tmp_path: Path) -> None:
    meta = load_ok(write(tmp_path, VALID_NOTE.rstrip("\n")))
    assert meta.lines[-1] == (7, "- [ ] Priya to send the quote")


def test_load_note_accepts_datetime_free_result_types() -> None:
    # The loader returns plain `date` objects, never `datetime`.
    meta = load_ok(FIXTURES / "frontmatter_valid.md")
    assert type(meta.meeting_date) is date and not isinstance(meta.meeting_date, datetime)
