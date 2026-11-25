"""The `ingest` use case: notes folder → stored sources → regrouped items → report (M7 spec).

Bad input never stops a run: every file is processed inside its own exception boundary and
transaction, so one broken note is reported and skipped while the others are stored.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal, Protocol

from actiontrack.clock import Clock
from actiontrack.config import Config
from actiontrack.dedup import DedupConfig, group_items
from actiontrack.errors import FatalError
from actiontrack.models import Flag, IngestReport, LineWarning, SkipReason, SkipRecord
from actiontrack.parsing.items import extract_items
from actiontrack.parsing.note_loader import load_note
from actiontrack.parsing.people import build_roster
from actiontrack.store.db import transaction
from actiontrack.store.repo import ItemFilter, ItemRepo, NoteRepo, PeopleRepo, SourceRepo

LOGGER_NAME = "actiontrack.ingest"
_log = logging.getLogger(LOGGER_NAME)

_NOTE_SUFFIX = ".md"
_MAX_WARNING_TEXT = 60
_COLUMN_GAP = "   "

_Outcome = Literal["unchanged"] | SkipRecord | list[LineWarning]


class ProgressSink(Protocol):
    def start(self, total: int) -> None: ...

    def advance(self, path: Path) -> None: ...

    def finish(self) -> None: ...


def check_folder(folder: Path) -> None:
    """`FatalError` unless `folder` is an existing directory (REQ-INGEST-08)."""
    if not folder.exists():
        raise FatalError(f"folder not found: {folder}", hint="check the path to your notes folder")
    if not folder.is_dir():
        raise FatalError(f"not a folder: {folder}", hint="pass the folder that holds the notes")


def scan(root: Path, *, recursive: bool) -> list[Path]:
    """`*.md` files (any case) under `root`, skipping hidden directories, sorted by POSIX path."""
    candidates = root.rglob("*") if recursive else root.glob("*")
    found = [
        p.resolve()
        for p in candidates
        if p.suffix.lower() == _NOTE_SUFFIX
        and p.is_file()
        and not any(part.startswith(".") for part in p.relative_to(root).parts[:-1])
    ]
    return sorted(found, key=lambda p: p.as_posix())


def run_ingest(
    folder: Path,
    *,
    recursive: bool,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Clock,
    fuzzy_enabled: bool | None = None,
    progress: ProgressSink | None = None,
) -> IngestReport:
    """Ingest every changed note under `folder`, then regroup all stored sources into items."""
    check_folder(folder)
    root = folder.resolve()
    files = scan(root, recursive=recursive)

    ingested = unchanged = 0
    skipped: list[SkipRecord] = []
    warnings: list[LineWarning] = []
    if progress is not None:
        progress.start(len(files))
    try:
        for path in files:
            outcome = _ingest_file_safely(path, conn=conn, cfg=cfg, clock=clock)
            if outcome == "unchanged":
                unchanged += 1
            elif isinstance(outcome, SkipRecord):
                skipped.append(outcome)
            else:
                ingested += 1
                warnings.extend(outcome)
            if progress is not None:
                progress.advance(path)
    finally:
        if progress is not None:
            progress.finish()

    notes = NoteRepo(conn)
    items = ItemRepo(conn)
    scanned = set(files)
    # Gap G4: only notes this scan could have seen count as deleted.
    gone = [
        p for p in notes.paths_under(root) if p not in scanned and (recursive or p.parent == root)
    ]
    dedup_cfg = DedupConfig(
        fuzzy_enabled=cfg.fuzzy_enabled if fuzzy_enabled is None else fuzzy_enabled,
        threshold=cfg.fuzzy_threshold,
    )
    # Regroup always (even when nothing changed), so that config changes apply to every item.
    with transaction(conn):
        for p in gone:
            notes.delete(p)
        sources = SourceRepo(conn).all()
        result = group_items(sources, items.existing(), dedup_cfg)
        items.apply_groups(result)

    rows = items.query(ItemFilter(include_orphaned=True), today=clock.today())
    counts = Counter(f for r in rows for f in r.flags)
    kinds = Counter(d.kind for d in result.decisions)
    return IngestReport(
        scanned=len(files),
        ingested=ingested,
        unchanged=unchanged,
        removed=len(gone),
        skipped=tuple(skipped),
        warnings=tuple(warnings),
        sources_total=len(sources),
        items_total=len(result.groups),
        exact_merges=kinds["exact"],
        fuzzy_merges=kinds["fuzzy"],
        flag_counts={f: counts[f] for f in Flag if counts[f]},
        decisions=result.decisions,
    )


def format_report(
    report: IngestReport,
    *,
    quiet: bool = False,
    verbose: bool = False,
    short_ids: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> list[str]:
    """The text report (root spec §9.1). `-q` keeps the two summary lines; `-v` adds merges."""
    r = report
    lines = [
        f"Scanned {r.scanned} files: {r.ingested} ingested, {r.unchanged} unchanged, "
        f"{len(r.skipped)} skipped, {r.removed} removed",
        f"Items: {r.sources_total} sources → {r.items_total} unique "
        f"({r.exact_merges} exact merges, {r.fuzzy_merges} fuzzy merges)",
    ]
    if quiet:
        return lines

    def where(path: Path, line_no: int | None = None) -> str:
        shown = _display_path(path, cwd)
        return shown if line_no is None else f"{shown}:{line_no}"

    if r.flag_counts:
        lines.append("Flags: " + ", ".join(f"{n} {f.value}" for f, n in r.flag_counts.items()))
    if r.skipped:
        lines.append("Skipped:")
        lines += _columns(
            (where(s.path, s.line_no), f"{s.reason.value}: {s.detail}") for s in r.skipped
        )
    if r.warnings:
        lines.append("Line warnings:")
        lines += _columns(
            (where(w.path, w.line_no), f'{w.code.value}: "{_truncate(w.text)}"') for w in r.warnings
        )
    if verbose and r.decisions:
        ids = short_ids or {}
        lines.append("Merges:")
        lines += [
            f"  {ids.get(d.item_id, d.item_id)} ← {where(*d.source)}  "
            f'{d.kind} {d.score:.1f}  "{d.matched_task_norm}"'
            for d in r.decisions
        ]
    return lines


def _ingest_file_safely(
    path: Path, *, conn: sqlite3.Connection, cfg: Config, clock: Clock
) -> _Outcome:
    """The per-file exception boundary (REQ-GEN-02): an unexpected error skips just this file."""
    try:
        return _ingest_file(path, conn=conn, cfg=cfg, clock=clock)
    except Exception as e:
        _log.debug("internal error while ingesting %s", path, exc_info=True)
        return SkipRecord(path, SkipReason.INTERNAL_ERROR, f"{type(e).__name__}: {e}")


def _ingest_file(path: Path, *, conn: sqlite3.Connection, cfg: Config, clock: Clock) -> _Outcome:
    notes = NoteRepo(conn)
    sha256 = _sha256(path)
    stored = notes.get(path)
    if sha256 is not None and stored is not None and stored.sha256 == sha256:
        if stored.status == "ok":
            return "unchanged"
        # Re-report the stored reason, so the user sees a broken note on every run.
        assert stored.skip_reason is not None
        return SkipRecord(path, SkipReason(stored.skip_reason), stored.skip_detail or "")

    loaded = load_note(path, date_order=cfg.date_order)
    if isinstance(loaded, SkipRecord):
        notes.upsert_skipped(loaded, sha256=sha256, now=clock.now())
        return loaded
    roster = build_roster(loaded.attendees_raw, domain=cfg.email_domain)
    items, warnings = extract_items(loaded, roster, date_order=cfg.date_order)
    with transaction(conn):
        notes.upsert_ok(loaded, now=clock.now())
        SourceRepo(conn).replace_for_note(path, items)
        PeopleRepo(conn).upsert_many(roster.attendees)
    return warnings


def _sha256(path: Path) -> str | None:
    """The file's hash, or None if it can't be read (the loader then reports why)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _display_path(path: Path, cwd: Path | None) -> str:
    """Relative to `cwd` when the path is below it, else absolute; always POSIX."""
    if cwd is not None:
        try:
            return path.relative_to(cwd).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _columns(rows: Iterable[tuple[str, str]]) -> list[str]:
    rows = list(rows)
    width = max(len(left) for left, _ in rows)
    return [f"  {left:<{width}}{_COLUMN_GAP}{right}" for left, right in rows]


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_WARNING_TEXT else text[: _MAX_WARNING_TEXT - 1] + "…"
