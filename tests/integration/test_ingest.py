from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from actiontrack.clock import FixedClock
from actiontrack.config import Config
from actiontrack.errors import FatalError
from actiontrack.models import Flag, IngestReport, NoteMeta, SkipReason
from actiontrack.services import ingest as ingest_module
from actiontrack.services.ingest import format_report, run_ingest, scan
from actiontrack.store.repo import ItemFilter, ItemRepo, ItemRow, NoteRepo, SourceRepo
from tests.integration.conftest import NOW

FIXTURES = Path(__file__).parent.parent / "fixtures" / "notes" / "ingest_basic"
CLOCK = FixedClock(date(2026, 11, 25), NOW)
TODAY = CLOCK.today()


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    """A fresh copy of the `ingest_basic` fixture folder."""
    dest = tmp_path / "notes"
    shutil.copytree(FIXTURES, dest)
    return dest.resolve()


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(db_path=tmp_path / "db.sqlite", outbox_dir=tmp_path / "outbox")


def ingest(folder: Path, conn: sqlite3.Connection, cfg: Config, **kwargs: object) -> IngestReport:
    kwargs.setdefault("recursive", True)
    return run_ingest(folder, conn=conn, cfg=cfg, clock=CLOCK, **kwargs)  # type: ignore[arg-type]


def all_items(conn: sqlite3.Connection) -> list[ItemRow]:
    return ItemRepo(conn).query(ItemFilter(include_orphaned=True), today=TODAY)


def item(conn: sqlite3.Connection, task: str) -> ItemRow:
    [row] = [r for r in all_items(conn) if r.task == task]
    return row


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


# --- scanning --------------------------------------------------------------------------------


def test_TC_M7_01_ingest_basic(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    r = ingest(notes, conn, cfg)
    assert (r.scanned, r.ingested, r.unchanged, r.removed) == (10, 8, 0, 0)
    assert sorted((s.path.name, s.reason) for s in r.skipped) == [
        ("2026-11-05-no-date.md", SkipReason.MISSING_DATE),
        ("2026-11-06-bad-yaml.md", SkipReason.INVALID_FRONTMATTER),
    ]
    assert (r.sources_total, r.items_total, r.exact_merges, r.fuzzy_merges) == (15, 13, 1, 1)
    assert r.flag_counts == {
        Flag.UNASSIGNED: 2,
        Flag.OWNER_NOT_ATTENDEE: 1,
        Flag.NO_DUE: 6,
        Flag.UNPARSED_DUE: 1,
    }
    [w] = r.warnings
    assert (w.path.name, w.line_no) == ("2026-11-18-standup.md", 5)
    assert all(p.suffix == ".md" for p in NoteRepo(conn).paths_under(notes))


def test_TC_M7_02_no_recursive(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    r = ingest(notes, conn, cfg, recursive=False)
    assert r.scanned == 9
    assert NoteRepo(conn).get(notes / "archive" / "2026-10-28-intro.md") is None


def test_TC_M7_03_hidden_dirs_and_suffix_case(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "x.md").write_text("# x", encoding="utf-8")
    (root / "NOTE.MD").write_text("# n", encoding="utf-8")
    (root / "sub.md").mkdir()  # a directory named like a note
    assert [p.name for p in scan(root.resolve(), recursive=True)] == ["NOTE.MD"]


def test_scan_sorts_by_posix_path_and_resolves(tmp_path: Path) -> None:
    for name in ("b.md", "a/z.md", "a.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x", encoding="utf-8")
    found = scan(tmp_path.resolve(), recursive=True)
    assert [p.relative_to(tmp_path.resolve()).as_posix() for p in found] == [
        "a.md",  # "." sorts before "/"
        "a/z.md",
        "b.md",
    ]
    assert all(p.is_absolute() for p in found)


@pytest.mark.parametrize("make", ["missing", "file"])
def test_missing_or_non_folder_is_fatal(
    make: str, tmp_path: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    target = tmp_path / "nope"
    if make == "file":
        target.write_text("x", encoding="utf-8")
    with pytest.raises(FatalError):
        ingest(target, conn, cfg)


# --- incremental runs ------------------------------------------------------------------------


def test_TC_M7_04_unchanged_rerun(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    ingest(notes, conn, cfg)
    before = list(conn.iterdump())
    r = ingest(notes, conn, cfg)
    assert (r.unchanged, r.ingested, len(r.skipped)) == (8, 0, 2)
    assert {s.reason for s in r.skipped} == {
        SkipReason.MISSING_DATE,
        SkipReason.INVALID_FRONTMATTER,
    }
    assert r.warnings == ()  # warnings come from parsing, and nothing was parsed
    assert (r.items_total, r.exact_merges, r.fuzzy_merges) == (13, 1, 1)
    assert list(conn.iterdump()) == before


def test_TC_M7_05_changed_note_replaces_sources(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    edit(notes / "2026-11-11-planning.md", "order new laptops", "order new monitors")
    r = ingest(notes, conn, cfg)
    assert (r.ingested, r.unchanged) == (1, 7)
    tasks = {s.task for s in SourceRepo(conn).all()}
    assert "order new monitors" in tasks
    assert "order new laptops" not in tasks
    assert (r.sources_total, r.items_total) == (15, 13)
    assert Flag.ORPHANED in item(conn, "order new laptops").flags


def test_TC_M7_06_deleted_line_orphans_item(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    edit(notes / "2026-11-18-standup.md", "- [ ] Anita to send the newsletter by 2026-11-21\n", "")
    ingest(notes, conn, cfg)
    row = item(conn, "send the newsletter")
    assert Flag.ORPHANED in row.flags
    assert row.status == "open"
    assert row.source_count == 0


def test_TC_M7_07_deleted_note_is_removed(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    (notes / "2026-11-20-demo.md").unlink()
    r = ingest(notes, conn, cfg)
    assert r.removed == 1
    assert NoteRepo(conn).get(notes / "2026-11-20-demo.md") is None
    assert all(s.note_path.name != "2026-11-20-demo.md" for s in SourceRepo(conn).all())
    assert Flag.ORPHANED in item(conn, "prepare the demo script").flags
    assert Flag.ORPHANED not in item(conn, "send the newsletter").flags


def test_TC_M7_08_other_folder_untouched(
    tmp_path: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    a = tmp_path / "notes"
    b = tmp_path / "notes2"  # a sibling whose name has `notes` as a prefix
    shutil.copytree(FIXTURES, a)
    b.mkdir()
    shutil.copy(FIXTURES / "2026-11-20-demo.md", b / "2026-11-21-demo.md")
    ingest(a, conn, cfg)
    r = ingest(b, conn, cfg)
    assert r.removed == 0
    assert len(NoteRepo(conn).paths_under(a.resolve())) == 10
    assert not any(Flag.ORPHANED in row.flags for row in all_items(conn))


def test_no_recursive_does_not_remove_subfolder_notes(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    r = ingest(notes, conn, cfg, recursive=False)
    assert r.removed == 0
    assert NoteRepo(conn).get(notes / "archive" / "2026-10-28-intro.md") is not None


def test_TC_M7_09_cli_done_survives_reingest(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    venue = item(conn, "book the venue for the offsite")
    assert ItemRepo(conn).mark_done(venue.id, now=NOW)
    edit(notes / "2026-11-04-sync.md", "Check the projector", "Check the projector cable")
    r = ingest(notes, conn, cfg)
    assert r.ingested == 1
    row = item(conn, "book the venue for the offsite")
    assert (row.id, row.status, row.done_source) == (venue.id, "done", "cli")


# --- failures --------------------------------------------------------------------------------


def test_TC_M7_10_internal_error_skips_only_that_file(
    notes: Path, conn: sqlite3.Connection, cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ingest_module.extract_items
    bad = notes / "2026-11-11-planning.md"

    def flaky(note: NoteMeta, *args: object, **kwargs: object) -> object:
        if note.path == bad:
            raise RuntimeError("boom")
        return real(note, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ingest_module, "extract_items", flaky)
    r = ingest(notes, conn, cfg)
    assert r.ingested == 7
    [failed] = [s for s in r.skipped if s.reason == SkipReason.INTERNAL_ERROR]
    assert (failed.path, failed.detail) == (bad, "RuntimeError: boom")
    assert NoteRepo(conn).get(bad) is None
    assert all(s.note_path != bad for s in SourceRepo(conn).all())


def test_internal_error_inside_transaction_rolls_back(
    notes: Path, conn: sqlite3.Connection, cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure hits after the note and its sources were written: nothing of it is kept."""

    def fail(self: object, attendees: object) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(ingest_module.PeopleRepo, "upsert_many", fail)
    r = ingest(notes, conn, cfg)
    assert r.ingested == 0
    assert sum(s.reason == SkipReason.INTERNAL_ERROR for s in r.skipped) == 8
    assert SourceRepo(conn).count() == 0
    assert [p.name for p in NoteRepo(conn).paths_under(notes)] == [
        "2026-11-05-no-date.md",
        "2026-11-06-bad-yaml.md",
    ]


def test_TC_M7_11_note_becomes_malformed(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    ingest(notes, conn, cfg)
    demo = notes / "2026-11-20-demo.md"
    edit(demo, "# Demo prep — 2026-11-20", "# Demo prep")
    r = ingest(notes, conn, cfg)
    assert [(s.path, s.reason) for s in r.skipped if s.path == demo] == [
        (demo, SkipReason.MISSING_DATE)
    ]
    stored = NoteRepo(conn).get(demo)
    assert stored is not None
    assert stored.status == "skipped"
    assert all(s.note_path != demo for s in SourceRepo(conn).all())
    assert Flag.ORPHANED in item(conn, "prepare the demo script").flags


def test_skipped_note_fixed_is_ingested(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    ingest(notes, conn, cfg)
    edit(notes / "2026-11-05-no-date.md", "# Hallway chat", "# Hallway chat — 2026-11-05")
    r = ingest(notes, conn, cfg)
    assert (r.ingested, len(r.skipped)) == (1, 1)
    assert item(conn, "buy coffee").owner_key == "rahul.mehta@coditas.com"


# --- regroup & progress ----------------------------------------------------------------------


def test_TC_M7_17_progress_sink(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    events: list[tuple[str, object]] = []

    class Spy:
        def start(self, total: int) -> None:
            events.append(("start", total))

        def advance(self, path: Path) -> None:
            events.append(("advance", path.name))

        def finish(self) -> None:
            events.append(("finish", None))

    ingest(notes, conn, cfg, progress=Spy())
    assert events[0] == ("start", 10)
    assert [e for e, _ in events[1:-1]] == ["advance"] * 10
    assert events[-1] == ("finish", None)


def test_TC_M7_18_regroup_applies_no_fuzzy(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    first = ingest(notes, conn, cfg)
    assert (first.items_total, first.fuzzy_merges) == (13, 1)
    r = ingest(notes, conn, cfg, fuzzy_enabled=False)
    assert (r.unchanged, r.items_total, r.fuzzy_merges) == (8, 14, 0)
    split = [row for row in all_items(conn) if "revised quote" in row.task]
    assert sorted(row.task for row in split) == [
        "send revised quotes to Acme",
        "send the revised quote to Acme",
    ]
    assert all(Flag.ORPHANED not in row.flags for row in split)
    # Fuzzy on again: both are existing items now, and two existing items are never merged
    # (that would drop an ID the user may already be using), so they stay apart.
    again = ingest(notes, conn, cfg)
    assert (again.items_total, again.fuzzy_merges) == (14, 0)


def test_config_fuzzy_disabled(notes: Path, conn: sqlite3.Connection, cfg: Config) -> None:
    no_fuzzy = Config(cfg.db_path, cfg.outbox_dir, fuzzy_enabled=False)
    assert ingest(notes, conn, no_fuzzy).fuzzy_merges == 0


# --- text report -----------------------------------------------------------------------------


def test_format_report_quiet_and_verbose(
    notes: Path, conn: sqlite3.Connection, cfg: Config
) -> None:
    r = ingest(notes, conn, cfg)
    assert format_report(r, quiet=True) == [
        "Scanned 10 files: 8 ingested, 0 unchanged, 2 skipped, 0 removed",
        "Items: 15 sources → 13 unique (1 exact merges, 1 fuzzy merges)",
    ]
    lines = format_report(r, verbose=True, short_ids={}, cwd=notes)
    assert "Skipped:" in lines
    assert (
        "  2026-11-06-bad-yaml.md:3   invalid_frontmatter: "
        + ("YAML error: expected ',' or ']', but got '<stream end>'")
        in lines
    )
    [fuzzy] = [line for line in lines if "← " in line and " fuzzy " in line]
    assert fuzzy.endswith('← 2026-11-09-review.md:6  fuzzy 98.1  "send revised quote to acme"')


def test_format_report_paths_outside_cwd_are_absolute(
    notes: Path, conn: sqlite3.Connection, cfg: Config, tmp_path: Path
) -> None:
    r = ingest(notes, conn, cfg)
    elsewhere = tmp_path / "elsewhere"
    lines = format_report(r, cwd=elsewhere)
    assert f"  {(notes / '2026-11-18-standup.md').as_posix()}:5   malformed_checkbox: " in (
        "\n".join(lines)
    )
    assert not any(line.startswith("Merges:") for line in lines)


def test_format_report_omits_empty_sections_and_truncates(tmp_path: Path) -> None:
    from actiontrack.models import LineWarning, WarningCode

    long = "-[ ] " + "x" * 100
    r = IngestReport(
        scanned=1, ingested=1, unchanged=0, removed=0, skipped=(),
        warnings=(LineWarning(tmp_path / "a.md", 2, WarningCode.MALFORMED_CHECKBOX, long),),
        sources_total=0, items_total=0, exact_merges=0, fuzzy_merges=0, flag_counts={},
        decisions=(),
    )  # fmt: skip
    lines = format_report(r, verbose=True, cwd=tmp_path)
    assert lines[2:] == ["Line warnings:", f'  a.md:2   malformed_checkbox: "{long[:59]}…"']
