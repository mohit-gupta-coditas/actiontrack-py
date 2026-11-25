# M7 — `ingest` Command

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M1, M2, M3 (via M4), M4, M5, M6 |
| **Files** | `actiontrack/services/ingest.py`, the `ingest` command in `actiontrack/cli.py` |
| **REQ IDs** | REQ-INGEST-01 … 09, REQ-GEN-02 |

## 1. Purpose
Orchestrate notes → DB: scan the folder, load and parse changed notes, persist the sources, regroup all items, and produce the
ingest report. Bad input never stops the run.

## 2. Interface

```python
class ProgressSink(Protocol):
    def start(self, total: int) -> None: ...
    def advance(self, path: Path) -> None: ...
    def finish(self) -> None: ...

def run_ingest(folder: Path, *, recursive: bool, conn: sqlite3.Connection, cfg: Config, clock: Clock,
               fuzzy_enabled: bool | None = None, progress: ProgressSink | None = None) -> IngestReport
```

CLI: `actiontrack ingest <folder> [--no-recursive] [--no-fuzzy] [--report-json PATH]`

## 3. Algorithm

1. **Validate**: if `folder` doesn't exist or isn't a directory → `FatalError` (exit 1) (REQ-INGEST-08).
2. **Scan** (REQ-INGEST-01): `rglob("*")` (or `glob` with `--no-recursive`), keeping files whose suffix is `.md` (case-insensitive).
   Hidden directories (`.git`, `.obsidian`, …) are skipped. Sorted by POSIX path. Paths are stored **resolved absolute**.
3. **Per file**, each wrapped in `try/except Exception` (REQ-GEN-02, REQ-INGEST-06):
   1. Compute sha256. If `NoteRepo.get(path)` has the same hash: status `ok` → `unchanged += 1`; status `skipped` → the
      stored reason is re-reported in `skipped` (the user still sees it every run). Either way, continue (REQ-INGEST-02).
   2. `load_note` (M1). A `SkipRecord` → `NoteRepo.upsert_skipped` (removes any old sources), add it to `skipped`.
   3. Else `build_roster` (M2) → `extract_items` (M4) → in **one transaction**: `NoteRepo.upsert_ok`, `SourceRepo.replace_for_note`
      (REQ-INGEST-03), `PeopleRepo.upsert_many`. Warnings collected. `ingested += 1`.
   4. An unexpected exception → roll back that file's transaction, add `SkipRecord(INTERNAL_ERROR, detail="<Type>: <msg>")`,
      continue. With `--debug` the traceback is logged.
   5. `progress.advance(path)`.
4. **Deleted files** (gap G4): `NoteRepo.paths_under(folder)` minus the scanned set → `NoteRepo.delete` (sources cascade). Counted
   as `removed`. Only paths under the resolved folder root are touched.
5. **Regroup** (always, even if nothing changed, so that config changes apply): `group_items(SourceRepo.all(), ItemRepo.existing(),
   DedupConfig(...))` → `ItemRepo.apply_groups(result)` in one transaction. Orphaned items get the flag and their status is untouched
   (REQ-INGEST-04). CLI-done is preserved by M5's rules (REQ-INGEST-05).
6. **Report** (REQ-INGEST-07): build the `IngestReport` (counts from steps 2–5, `flag_counts` over the current items, decisions).

## 4. Output

**stdout** (text report, root spec §9.1 format):
```
Scanned 34 files: 29 ingested, 2 unchanged, 3 skipped, 0 removed
Items: 112 sources → 87 unique (19 exact merges, 6 fuzzy merges)
Flags: 5 unassigned, 2 ambiguous_owner, 4 no_due, 1 unparsed_due
Skipped:
  notes/2026-10-03-standup.md   missing_date: no meeting date found
Line warnings:
  notes/2026-11-02-sync.md:41   malformed_checkbox: "-[ ] Rahul …"
```
- Paths are printed relative to the current working directory when possible.
- Zero-count sections are omitted. `-q` → only the first two lines.
- `-v` → adds a `Merges:` section listing each `MergeDecision` (`a3f91c ← notes/x.md:12  fuzzy 91.7  "send revised quote"`).
- `--report-json PATH` → writes `IngestReport.to_json()` (with `schema_version: 1`) to PATH. A write failure is a `UserInputError`.
- **Progress** (REQ-INGEST-09): a rich progress bar on **stderr**, only when stderr is a TTY and `-q` is not set.

## 5. Exit codes (REQ-INGEST-08)
`0` when the run completes, even with skipped files or warnings. `1` for a missing folder or a DB that can't be opened. `130` on Ctrl-C (the current
file's transaction is rolled back. Files already committed stay committed).

## 6. Out of scope
Parsing details (M1–M4), grouping rules (M5), SQL (M6).

## 7. Open questions
G4 (deleted files) needs confirming.
