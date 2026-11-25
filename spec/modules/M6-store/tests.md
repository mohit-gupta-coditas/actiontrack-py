# M6 — Test Cases

Location: `tests/integration/store/`. A fresh DB per test (`tmp_path / "t.db"`, or `:memory:` where WAL isn't the subject).

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M6-01 | A path in a dir that doesn't exist | `connect` | Dir created. All tables exist, `user_version == 1` | REQ-STORE-01, 03, 04 |
| TC-M6-02 | A connected DB | `connect` again | No error, migrations not re-applied | REQ-STORE-03 |
| TC-M6-03 | DB with `user_version = 99` | `connect` | `FatalError` "newer actiontrack" | REQ-STORE-03 |
| TC-M6-04 | A file DB | `connect` | `journal_mode == wal`, `busy_timeout == 5000`, `foreign_keys == 1` | REQ-STORE-05 |
| TC-M6-05 | Two connections. A holds `BEGIN IMMEDIATE` briefly (<1 s) | B writes | B waits and succeeds | REQ-STORE-05 |
| TC-M6-06 | — | `EXPLAIN QUERY PLAN` for owner and status/due queries | Uses `ix_items_owner` / `ix_items_status_due` | REQ-STORE-06 |
| TC-M6-07 | `transaction` block raising `KeyboardInterrupt` after an insert | — | Row not present afterwards. Exception propagated | REQ-STORE-01 |
| TC-M6-08 | `SourceRepo.replace_for_note` with 3 `ParsedItem`s, then `all()` | — | Round-trips equal (dates, flags, candidates, checked) | REQ-STORE-01 |
| TC-M6-09 | Note with sources | `NoteRepo.upsert_skipped` | Sources for that note deleted, status `skipped`, reason stored | REQ-STORE-01 |
| TC-M6-10 | Attendee with an explicit email stored, later upserted without one | `upsert_many` | Email kept | REQ-STORE-01 |
| TC-M6-11 | People Priya Shah, Priya Nair, Rahul Mehta | `find("priya")`, `find("Priya Nair")`, `find("rahul.mehta@coditas.com")` | 2, 1, 1 results | REQ-STORE-01 |
| TC-M6-12 | Items: open due yesterday, open due tomorrow, done due yesterday, open no due. `FixedClock` today | `query(status="overdue")` | Only the first. `is_overdue` true only for it | REQ-STORE-02 |
| TC-M6-13 | Same data | `query(status="open")` | Open items, including the overdue one (3) | REQ-STORE-02 |
| TC-M6-14 | Same data, `today` moved forward 2 days | `query(status="overdue")` | Now includes the "tomorrow" item (nothing stored changed) | REQ-STORE-02 |
| TC-M6-15 | `apply_groups` with an orphaned id | then `query()` / `query(flag=ORPHANED)` | Hidden by default. Shown with the flag. Status unchanged | REQ-STORE-01 |
| TC-M6-16 | Orphaned item regains a source on the next `apply_groups` | — | `ORPHANED` flag removed | REQ-STORE-01 |
| TC-M6-17 | `mark_done` on an open item, then again | — | First → True, status done, `done_source='cli'`, `done_at=now`. Second → False | REQ-STORE-01 |
| TC-M6-18 | Mixed due dates incl. NULL | `query()` | Ordered by due asc, NULLs last, then owner, then id | REQ-STORE-01 |
| TC-M6-19 | `query(due_before=11-20)` | — | Only items with due < 11-20, no NULL due | REQ-STORE-01 |
| TC-M6-20 | `DraftRepo.record` | — | Row stored, `item_ids` JSON | REQ-STORE-01 |
| TC-M6-21 | DB path in a read-only directory (skipped on Windows if it can't be simulated) | `connect` | `FatalError` naming the path | REQ-STORE-04 |
