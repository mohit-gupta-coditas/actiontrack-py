"""M12 end-to-end acceptance tests (M12 tests.md, root spec §16). The CLI runs as a subprocess."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import FAKE_SERVER, NOTES, TODAY, Cli, make_cli, same_file

pytestmark = pytest.mark.slow

SEND_TOOLS = ("send_message", "reply", "forward")


def all_items(cli: Cli) -> list[dict[str, Any]]:
    """Open and done items: most known duplicates end with a `[x]` in a later note (G32)."""
    return cli.items() + cli.items("--status", "done")


def skipped_section(stdout: str) -> dict[str, str]:
    """`Skipped:` lines of the ingest report → {path: reason code}."""
    section = stdout.split("Skipped:\n", 1)[1] if "Skipped:\n" in stdout else ""
    out: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("  "):
            break
        m = re.match(r"\s+(\S+?)(?::\d+)?\s+([a-z_]+):", line)
        assert m, line
        out[m[1]] = m[2]
    return out


def dump(db: Path) -> list[str]:
    """Every row of every table, without the `ingested_at` timestamps (TC-M12-09)."""
    conn = sqlite3.connect(db)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        rows: list[str] = []
        for t in sorted(tables):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})") if r[1] != "ingested_at"]
            select = ", ".join(f'"{c}"' for c in cols)
            rows += [
                f"{t}: {r!r}" for r in conn.execute(f'SELECT {select} FROM "{t}" ORDER BY 1, 2')
            ]
        rows += [r for r in conn.iterdump() if r.startswith("CREATE")]
        return rows
    finally:
        conn.close()


def test_TC_M12_01_ingest_sample_lists_every_malformed_file(
    sample_ingest: tuple[Cli, Any], expected: dict[str, Any]
) -> None:
    cli, r = sample_ingest
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    assert skipped_section(r.stdout) == expected["skipped"]
    report = json.loads(cli.db.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["items_total"] >= expected["min_unique_items"]


def test_TC_M12_02_duplicate_appears_once_with_sources_and_latest_due(
    ingested: Cli, expected: dict[str, Any]
) -> None:
    items = all_items(ingested)
    for dup in expected["duplicates"]:
        matches = [
            i
            for i in items
            if i["owner"] is not None
            and i["owner"]["key"] == dup["owner"]
            and dup["task_contains"].lower() in i["task"].lower()
        ]
        assert len(matches) == 1, (dup, [m["task"] for m in matches])
        item = matches[0]
        assert len(item["sources"]) >= dup["min_sources"], (dup, item["sources"])
        if "due" in dup:
            assert item["due_date"] == str(dup["due"]), (dup, item)
        if "status" in dup:
            assert item["status"] in (
                ("open", "overdue") if dup["status"] == "open" else (dup["status"],)
            ), (dup, item)


def test_TC_M12_03_shared_first_name_is_ambiguous_and_unassigned(
    ingested: Cli, expected: dict[str, Any]
) -> None:
    items = ingested.items("--flag", "ambiguous_owner")
    for amb in expected["ambiguous"]:
        hits = [
            i
            for i in items
            if any(
                same_file(s["path"], amb["file"]) and s["line"] == amb["line"] for s in i["sources"]
            )
        ]
        assert len(hits) == 1, amb
        assert hits[0]["owner"] is None
        assert "ambiguous_owner" in hits[0]["flags"]


def test_TC_M12_04_unassigned_listed_and_undated_never_overdue(ingested: Cli) -> None:
    assert ingested.items("--unassigned")
    overdue = ingested.items("--status", "overdue")
    assert overdue
    assert all(i["due_date"] is not None for i in overdue)


def test_TC_M12_05_by_friday_on_a_wednesday(tmp_path: Path, expected: dict[str, Any]) -> None:
    notes = tmp_path / "notes"
    shutil.copytree(NOTES, notes)
    (notes / "2026-11-18-fixture.md").write_text(
        "# Meeting: Fixture\nDate: 2026-11-18\nAttendees: Rahul Mehta\n\n"
        "## Action items\n- [ ] Rahul to send quote by Friday\n",
        encoding="utf-8",
    )
    cli = make_cli(tmp_path / "cli")
    r = cli("ingest", str(notes))
    assert r.returncode == 0, r.stderr
    # The sample has two Rahuls, so the bare first name would be ambiguous (G33).
    items = cli.items("--owner", "Rahul Mehta")
    hits = [i for i in items if i["task"] == "send quote"]
    assert [i["due_date"] for i in hits] == ["2026-11-20"]


def test_TC_M12_06_overdue_rows_are_red_and_marked(ingested: Cli) -> None:
    overdue = ingested.items("--status", "overdue")
    assert overdue
    assert all(date.fromisoformat(i["due_date"]) < date.fromisoformat(TODAY) for i in overdue)

    wide = {"COLUMNS": "250"}
    plain = ingested("list", "--status", "overdue", env=wide)
    assert plain.returncode == 0, plain.stderr
    assert "\x1b[" not in plain.stdout
    for i in overdue:
        row = next(line for line in plain.stdout.splitlines() if line.find(i["short_id"]) >= 0)
        assert "⚠ overdue" in row, row

    coloured = ingested("list", "--status", "overdue", env={**wide, "FORCE_COLOR": "1"})
    assert coloured.returncode == 0, coloured.stderr
    for i in overdue:
        row = next(line for line in coloured.stdout.splitlines() if i["short_id"] in line)
        assert "\x1b[31m" in row, repr(row)


def test_TC_M12_07_done_survives_reingest_of_a_changed_note(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    shutil.copytree(NOTES, notes)
    cli = make_cli(tmp_path / "cli")
    assert cli("ingest", str(notes)).returncode == 0
    item = next(i for i in cli.items() if i["owner"] is not None and len(i["sources"]) == 1)
    r = cli("done", item["short_id"])
    assert r.returncode == 0, r.stderr

    note = Path(item["sources"][0]["path"])
    note.write_text(note.read_text(encoding="utf-8") + "\nEdited after the meeting.\n", "utf-8")
    r = cli("ingest", str(notes))
    assert r.returncode == 0, r.stderr
    assert ": 1 ingested," in r.stdout.splitlines()[0]
    assert item["id"] in [i["id"] for i in cli.items("--status", "done")]


def test_TC_M12_08_followup_creates_exactly_one_draft_and_never_sends(
    ingested: Cli, expected: dict[str, Any], tmp_path: Path
) -> None:
    calls = tmp_path / "calls.json"
    server = json.dumps([str(FAKE_SERVER), str(calls)])
    ingested.config.write_text(
        ingested.config.read_text(encoding="utf-8")
        + f'[gmail_mcp]\ntransport = "stdio"\ncommand = {json.dumps(sys.executable)}\n'
        f"args = {server}\n",
        encoding="utf-8",
    )
    r = ingested("followup", expected["followup"]["owner"])
    assert r.returncode == 0, r.stderr
    log = json.loads(calls.read_text(encoding="utf-8"))
    assert [c["name"] for c in log] == ["create_draft"]
    assert log[0]["arguments"]["to"] == [expected["followup"]["to"]]
    assert not [c for c in log if c["name"] in SEND_TOOLS]
    assert "r-e2e-1" in r.stdout or "mail.example" in r.stdout


def test_TC_M12_09_second_ingest_changes_nothing(ingested: Cli) -> None:
    before = dump(ingested.db)
    r = ingested("ingest", "notes")
    assert r.returncode == 0, r.stderr
    assert ": 0 ingested," in r.stdout.splitlines()[0]
    assert dump(ingested.db) == before


def test_TC_M12_10_list_json_is_pure_json(ingested: Cli) -> None:
    r = ingested("list", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["schema_version"] == 1
    assert data["items"]


COMMANDS = (
    ("--help",),
    ("ingest", "--help"),
    ("list", "--help"),
    ("done", "--help"),
    ("followup", "--help"),
    ("config", "show", "--help"),
)

USER_ERRORS = (
    (("done", "zz"), 2),
    (("list", "--owner", "Nobody"), 2),
    (("list", "--due-before", "junk"), 2),
    (("followup", "Nobody"), 2),
    (("ingest", "missing/"), 1),
)


@pytest.mark.parametrize("args", COMMANDS, ids=" ".join)
def test_TC_M12_11_help_has_examples(cli: Cli, args: tuple[str, ...]) -> None:
    r = cli(*args)
    assert r.returncode == 0, r.stderr
    if args != ("--help",):
        assert "Examples:" in r.stdout


@pytest.mark.parametrize(
    ("args", "code"), USER_ERRORS, ids=lambda v: " ".join(v) if isinstance(v, tuple) else str(v)
)
def test_TC_M12_11_user_errors_have_no_traceback(
    cli: Cli, args: tuple[str, ...], code: int
) -> None:
    r = cli(*args)
    assert r.returncode == code, (r.stdout, r.stderr)
    assert "Error:" in r.stderr
    assert "Traceback" not in r.stderr + r.stdout
