from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from actiontrack.cli import run
from actiontrack.store.db import connect
from actiontrack.store.repo import ItemRepo
from tests.integration.conftest import SEEDED, group, seed, src

TODAY = date(2026, 11, 25)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty DB file, used by the CLI through ACTIONTRACK_DB; today is 2026-11-25."""
    path = tmp_path / "db.sqlite"
    monkeypatch.setenv("ACTIONTRACK_DB", str(path))
    monkeypatch.setenv("ACTIONTRACK_TODAY", TODAY.isoformat())
    monkeypatch.setenv("COLUMNS", "200")  # keep table rows on one line
    return path


@pytest.fixture
def seeded(db: Path) -> Path:
    conn = connect(db)
    try:
        seed(conn)
    finally:
        conn.close()
    return db


def short(name: str) -> str:
    return SEEDED[name][:6]


def rows(out: str) -> dict[str, str]:
    """Table lines by the short id they start with (after the border)."""
    found: dict[str, str] = {}
    for line in out.splitlines():
        cells = line.strip("│┃| ").split()
        if cells and cells[0] in {short(n) for n in SEEDED}:
            found[cells[0]] = line
    return found


# --- list --------------------------------------------------------------------------------------


def test_TC_M8_01_default_list(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list"]) == 0
    captured = capsys.readouterr()
    expected = ("quote", "venue", "projector", "budget", "agenda", "invoice", "contract")
    assert list(rows(captured.out)) == [short(n) for n in expected]
    assert captured.err == "7 items (2 overdue)\n"


def test_TC_M8_02_list_overdue(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--status", "overdue"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("quote"), short("venue")]


def test_TC_M8_03_list_done(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--status", "done"]) == 0
    out = capsys.readouterr().out
    assert list(rows(out)) == [short("slides")]
    assert "done" in rows(out)[short("slides")]


def test_TC_M8_04_list_owner(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--owner", "Rahul"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("venue"), short("agenda")]


def test_TC_M8_05_list_owner_email(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--owner", "priya.nair@coditas.com"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("contract")]


def test_TC_M8_06_ambiguous_owner(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--owner", "Priya"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert 'Error: "Priya" matches 2 people' in captured.err
    assert "Priya Shah <priya.shah@coditas.com>" in captured.err
    assert "Priya Nair <priya.nair@coditas.com>" in captured.err


def test_TC_M8_07_unknown_owner(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--owner", "Zed"]) == 2
    captured = capsys.readouterr()
    assert 'no person matches "Zed"' in captured.err
    assert captured.out == ""


def test_TC_M8_08_due_before(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--due-before", "2026-11-22"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("quote"), short("venue")]


def test_TC_M8_09_due_before_invalid(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--due-before", "not a date"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_TC_M8_10_unassigned(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--unassigned"]) == 0
    out = capsys.readouterr().out
    assert list(rows(out)) == [short("projector"), short("budget")]
    assert "—" in rows(out)[short("projector")]
    assert "? Priya (ambiguous)" in rows(out)[short("budget")]


def test_TC_M8_11_flag_ambiguous(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--flag", "ambiguous_owner"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("budget")]


def test_TC_M8_12_flag_orphaned(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list", "--flag", "orphaned"]) == 0
    assert list(rows(capsys.readouterr().out)) == [short("orphan")]


def test_TC_M8_13_owner_and_unassigned(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--owner", "Rahul", "--unassigned"]) == 2
    captured = capsys.readouterr()
    assert "--owner and --unassigned" in captured.err
    assert captured.out == ""


def test_TC_M8_14_table_no_color(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "list"]) == 0
    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if "ID" in line)
    for column in ("ID", "Owner", "Task", "Due", "Status", "Src"):
        assert column in header
    table = rows(out)
    for name in ("quote", "venue"):
        assert "⚠ overdue" in table[short(name)]
    assert "⚠" not in table[short("agenda")]
    quote = table[short("quote")]
    assert all(s in quote for s in ("Priya Shah", "send the revised quote", "2026-11-20", " 2 "))
    assert "—" in table[short("contract")]  # no due date
    assert "\x1b[" not in out


def test_TC_M8_15_overdue_row_red(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from actiontrack import console

    real = console.Console

    def forced(*args: Any, **kwargs: Any) -> Console:
        # A terminal with plain ANSI colours, also on Windows.
        kwargs.update(force_terminal=True, color_system="standard", legacy_windows=False)
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(console, "Console", forced)
        assert run(["list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    red = "[31m"
    assert red in next(line for line in lines if "send the revised quote" in line)
    assert red not in next(line for line in lines if "draft the agenda" in line)


def test_TC_M8_16_json(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema_version"] == 1
    assert data["today"] == "2026-11-25"
    assert data["generated_at"].startswith("2026-11-25T00:00:00")
    assert data["filters"] == {
        "owner": None, "status": "open", "due_before": None, "unassigned": False, "flag": None
    }  # fmt: skip
    items = {i["id"]: i for i in data["items"]}
    assert len(items) == 7
    quote = items[SEEDED["quote"]]
    assert quote == {
        "id": SEEDED["quote"],
        "short_id": short("quote"),
        "owner": {"key": "priya.shah@coditas.com", "name": "Priya Shah"},
        "task": "send the revised quote",
        "due_date": "2026-11-20",
        "status": "overdue",
        "flags": [],
        "sources": [
            {"path": "notes/2026-11-11-kickoff.md", "line": 4, "meeting_date": "2026-11-11",
             "title": None},
            {"path": "notes/2026-11-18-sync.md", "line": 3, "meeting_date": "2026-11-18",
             "title": None},
        ],
    }  # fmt: skip
    assert items[SEEDED["budget"]]["owner"] is None
    assert items[SEEDED["contract"]]["due_date"] is None
    assert "items (" not in captured.out
    assert captured.err == ""


def test_TC_M8_17_json_done(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--json", "--status", "done", "--owner", "priya shah"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["filters"]["status"] == "done"
    assert data["filters"]["owner"] == "priya shah"
    assert [i["id"] for i in data["items"]] == [SEEDED["slides"]]
    assert {i["status"] for i in data["items"]} == {"done"}


def test_TC_M8_18_empty_db(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "No items match.\n"


def test_json_empty(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["items"] == []
    assert captured.err == ""


def test_quiet_list(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["-q", "--no-color", "list"]) == 0
    captured = capsys.readouterr()
    assert short("quote") in captured.out
    assert captured.err == ""


def test_markup_in_task_is_literal(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    conn = connect(db)
    try:
        seed(conn, group(src(None, "update [bold]docs[/bold]", "2026-11-18", line=20,
                             path="notes/2026-11-18-sync.md")))  # fmt: skip
    finally:
        conn.close()
    assert run(["--no-color", "list", "--unassigned"]) == 0
    assert "update [bold]docs[/bold]" in capsys.readouterr().out


def test_bad_status_choice(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--status", "late"]) == 2
    assert "late" in capsys.readouterr().err


# --- done --------------------------------------------------------------------------------------


def test_TC_M8_19_done(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["done", short("quote")]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"✓ {short('quote')}  send the revised quote  (Priya Shah)\n"
    assert run(["--no-color", "list", "--status", "done"]) == 0
    assert short("quote") in rows(capsys.readouterr().out)


def test_TC_M8_20_done_four_char_prefix(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prefix = SEEDED["agenda"][:4]
    assert sum(i.startswith(prefix) for i in SEEDED.values()) == 1
    assert run(["done", prefix.upper()]) == 0
    assert capsys.readouterr().out.startswith(f"✓ {short('agenda')}  draft the agenda")


def test_TC_M8_21_done_twice(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["done", short("venue")]) == 0
    capsys.readouterr()
    assert run(["done", short("venue")]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{short('venue')} is already done.\n"


def test_TC_M8_22_ambiguous_prefix(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = "abcd1" + "0" * 35, "abcd2" + "0" * 35
    note = "notes/2026-11-18-sync.md"
    conn = connect(db)
    try:
        seed(
            conn,
            group(src(None, "first", "2026-11-18", line=30, path=note), item_id=a),
            group(src(None, "second", "2026-11-18", line=31, path=note), item_id=b),
        )
    finally:
        conn.close()
    assert run(["done", "abcd"]) == 2
    err = capsys.readouterr().err
    assert 'id "abcd" matches 2 items' in err
    assert "abcd10, abcd20" in err


@pytest.mark.parametrize("prefix", ["ffff", "ab", "zzzz"])
def test_TC_M8_23_unknown_or_bad_prefix(
    seeded: Path, prefix: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert not any(i.startswith("ffff") for i in SEEDED.values())
    assert run(["done", prefix]) == 2
    assert capsys.readouterr().out == ""


def test_TC_M8_24_done_in_db(seeded: Path) -> None:
    assert run(["done", short("contract")]) == 0
    conn = connect(seeded)
    try:
        row = ItemRepo(conn).get(SEEDED["contract"], today=TODAY)
    finally:
        conn.close()
    assert row is not None
    assert (row.status, row.done_source) == ("done", "cli")
    assert row.done_at is not None and row.done_at.date() == TODAY


def test_done_without_owner(seeded: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["done", short("projector")]) == 0
    assert capsys.readouterr().out == f"✓ {short('projector')}  fix the projector\n"
