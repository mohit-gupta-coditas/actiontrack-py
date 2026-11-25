# M7 — Test Cases

Location: `tests/integration/test_ingest.py` (service) and `tests/integration/test_cli_ingest.py` (CLI via `CliRunner`).
Fixture folder `tests/fixtures/notes/ingest_basic/` (copied to `tmp_path` per test): 6 valid notes, 2 malformed (no date, bad YAML),
1 with a malformed checkbox, a nested sub-folder with 1 note, and a `.txt` file.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M7-01 | `ingest_basic` | `run_ingest(recursive=True)` | scanned 10 (.md only), ingested 8, skipped 2, the `.txt` ignored | REQ-INGEST-01 |
| TC-M7-02 | Same | `recursive=False` | The sub-folder note is not scanned | REQ-INGEST-01 |
| TC-M7-03 | Folder with `.git/x.md` and `NOTE.MD` | `run_ingest` | `.git` skipped, `NOTE.MD` included | REQ-INGEST-01 |
| TC-M7-04 | Ingested once | Run again unchanged | `unchanged == 8`, `ingested == 0`, `skipped == 2` (re-reported from the stored reason), DB items byte-identical (dump compare) | REQ-INGEST-02 |
| TC-M7-05 | Ingested. One note edited (an item's task text changed) | Re-run | `ingested == 1`. The old source is gone, the new source exists. Item count consistent | REQ-INGEST-03 |
| TC-M7-06 | Ingested. An item line deleted from its only note | Re-run | Item still in the DB with flag `orphaned`. Status unchanged | REQ-INGEST-04 |
| TC-M7-07 | Ingested. A note file deleted | Re-run | `removed == 1`. Its sources removed. Items that came only from it are orphaned | REQ-INGEST-04 (G4) |
| TC-M7-08 | Ingest folder A, then folder B (disjoint) | Run on B | Notes from A not removed | REQ-INGEST-04 (G4) |
| TC-M7-09 | Item marked done via `ItemRepo.mark_done`. Note touched (changed) | Re-run | Item still done, `done_source == 'cli'` | REQ-INGEST-05 |
| TC-M7-10 | `extract_items` monkeypatched to raise `RuntimeError` for one specific file | `run_ingest` | That file → skipped `internal_error`. All other files ingested. No partial rows for the failing file | REQ-INGEST-06, REQ-GEN-02 |
| TC-M7-11 | A previously valid note becomes malformed | Re-run | Note status `skipped`. Its sources removed. Its items orphaned | REQ-INGEST-06 |
| TC-M7-12 | `ingest_basic` | CLI `ingest <dir>` | stdout has `Scanned`, `Items:`, `Skipped:` with both malformed files + reasons, `Line warnings:` with file:line. Exit 0 | REQ-INGEST-07, 08 |
| TC-M7-13 | Same | CLI `--report-json out.json` | A valid JSON file with `schema_version`, counts, and the skipped list matching the text | REQ-INGEST-07 |
| TC-M7-14 | Same | CLI `-q` | stdout only has the 2 summary lines | REQ-INGEST-07 |
| TC-M7-15 | Same, with 1 fuzzy merge in the fixtures | CLI `-v` | stdout has a `Merges:` line with the score | REQ-INGEST-07 |
| TC-M7-16 | A path that doesn't exist | CLI `ingest nope/` | `Error:` on stderr, exit 1 | REQ-INGEST-08 |
| TC-M7-17 | Non-TTY (CliRunner) | CLI `ingest` | No progress output on stdout or stderr. A `ProgressSink` spy in a service test sees start/advance×N/finish | REQ-INGEST-09 |
| TC-M7-18 | Ingested with fuzzy on (1 fuzzy merge) | Re-run with `--no-fuzzy` and no file changes | Regrouping applies: the merged item splits into 2 | REQ-INGEST-02 (regroup always) |
| TC-M7-19 | `KeyboardInterrupt` injected while processing file 3 of 8 | CLI | Exit 130. Files 1–2 committed. File 3 has no rows | REQ-INGEST-06 |
