from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from actiontrack import cli
from actiontrack.cli import run
from actiontrack.services import ingest as ingest_module
from actiontrack.store.db import connect
from actiontrack.store.repo import NoteRepo, SourceRepo

FIXTURES = Path(__file__).parent.parent / "fixtures" / "notes" / "ingest_basic"


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """cwd with a copy of `ingest_basic` in `notes/`, so report paths print as `notes/...`."""
    shutil.copytree(FIXTURES, tmp_path / "notes")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACTIONTRACK_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("ACTIONTRACK_TODAY", "2026-11-25")
    return tmp_path


def test_TC_M7_12_text_report(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["ingest", "notes"]) == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == "Scanned 10 files: 8 ingested, 0 unchanged, 2 skipped, 0 removed"
    assert lines[1] == "Items: 15 sources → 13 unique (1 exact merges, 1 fuzzy merges)"
    assert lines[2].startswith("Flags: 2 unassigned")
    skipped = lines[lines.index("Skipped:") + 1 : lines.index("Line warnings:")]
    assert [line.split()[:2] for line in skipped] == [
        ["notes/2026-11-05-no-date.md", "missing_date:"],
        ["notes/2026-11-06-bad-yaml.md:3", "invalid_frontmatter:"],
    ]
    assert lines[lines.index("Line warnings:") + 1].startswith(
        "  notes/2026-11-18-standup.md:5   malformed_checkbox:"
    )
    assert "Merges:" not in lines
    assert captured.err == ""


def test_TC_M7_13_report_json(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["ingest", "notes", "--report-json", "out.json"]) == 0
    data = json.loads((workdir / "out.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert (data["scanned"], data["ingested"], data["unchanged"], data["removed"]) == (10, 8, 0, 0)
    assert (data["items_total"], data["exact_merges"], data["fuzzy_merges"]) == (13, 1, 1)
    text = capsys.readouterr().out
    for s in data["skipped"]:
        name = Path(s["path"]).name
        assert name in text
        assert f"{s['reason']}: {s['detail']}" in text
    assert data["flag_counts"]["unassigned"] == 2


def test_report_json_write_failure(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["ingest", "notes", "--report-json", "missing/out.json"]) == 2
    captured = capsys.readouterr()
    assert "Error: cannot write the JSON report" in captured.err
    assert captured.out.startswith("Scanned 10 files")  # the run itself completed


def test_TC_M7_14_quiet(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["-q", "ingest", "notes"]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "Scanned 10 files: 8 ingested, 0 unchanged, 2 skipped, 0 removed",
        "Items: 15 sources → 13 unique (1 exact merges, 1 fuzzy merges)",
    ]
    assert captured.err == ""


def test_TC_M7_15_verbose_merges(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["-v", "ingest", "notes"]) == 0
    lines = capsys.readouterr().out.splitlines()
    merges = lines[lines.index("Merges:") + 1 :]
    assert len(merges) == 2
    [fuzzy] = [line for line in merges if " fuzzy " in line]
    assert "← notes/2026-11-09-review.md:6  fuzzy 98.1" in fuzzy
    short_id = fuzzy.split()[0]
    assert len(short_id) == 6
    assert all(c in "0123456789abcdef" for c in short_id)


def test_TC_M7_16_missing_folder(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["ingest", "nope/"]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("Error: folder not found: nope")
    assert captured.out == ""
    assert not (workdir / "db.sqlite").exists()


def test_TC_M7_17_no_progress_without_tty(workdir: Path) -> None:
    result = CliRunner().invoke(cli.app, ["ingest", "notes"])
    assert result.exit_code == 0
    assert "Ingesting" not in result.stdout
    assert result.stderr == ""


def test_progress_bar_on_tty(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    real = cli._RichProgress

    class Recording(real):  # type: ignore[valid-type,misc]
        def start(self, total: int) -> None:
            seen.append(total)
            super().start(total)

    monkeypatch.setattr(cli, "_RichProgress", Recording)
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: True))
    assert run(["ingest", "notes"]) == 0
    assert seen == [10]


def test_TC_M7_18_no_fuzzy_splits(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["-q", "ingest", "notes"]) == 0
    assert run(["-q", "ingest", "notes", "--no-fuzzy"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Scanned 10 files: 8 ingested, 0 unchanged, 2 skipped, 0 removed",
        "Items: 15 sources → 13 unique (1 exact merges, 1 fuzzy merges)",
        "Scanned 10 files: 0 ingested, 8 unchanged, 2 skipped, 0 removed",
        "Items: 15 sources → 14 unique (1 exact merges, 0 fuzzy merges)",
    ]


def test_TC_M7_19_interrupt_rolls_back_current_file(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl-C after file 3's note and sources were written: files 1, 2 stay; file 3 has no rows."""
    calls: list[int] = []
    real = ingest_module.PeopleRepo.upsert_many

    def interrupt_third(self: ingest_module.PeopleRepo, attendees: object) -> None:
        calls.append(1)
        if len(calls) == 3:
            raise KeyboardInterrupt
        real(self, attendees)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module.PeopleRepo, "upsert_many", interrupt_third)
    assert run(["ingest", "notes"]) == 130
    assert "Interrupted" in capsys.readouterr().err

    conn = connect(workdir / "db.sqlite")
    try:
        stored = {p.name: NoteRepo(conn).get(p) for p in NoteRepo(conn).paths_under(workdir)}
        with_sources = {s.note_path.name for s in SourceRepo(conn).all()}
    finally:
        conn.close()
    # Scan order (POSIX path): 2026-11-02-kickoff.md, 2026-11-04-sync.md, then (skipped)
    # 2026-11-05-no-date.md, 2026-11-06-bad-yaml.md, then 2026-11-09-review.md, ...
    assert with_sources == {"2026-11-02-kickoff.md", "2026-11-04-sync.md"}
    assert "2026-11-09-review.md" not in stored


def test_debug_logs_traceback_of_skipped_file(
    workdir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest_module, "extract_items", boom)
    logger = logging.getLogger(ingest_module.LOGGER_NAME)
    try:
        assert run(["--debug", "ingest", "notes"]) == 0
    finally:
        logger.setLevel(logging.NOTSET)
    captured = capsys.readouterr()
    assert "Traceback" in captured.err
    assert "internal_error: RuntimeError: boom" in captured.out
