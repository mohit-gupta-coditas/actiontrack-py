# M8 — Test Cases

Location: `tests/integration/test_query.py` and `tests/integration/test_cli_list_done.py`. Seeded DB fixture (`seeded_db`) with:
Priya Shah, Priya Nair, Rahul Mehta (attendees) and Vikram Rao (an owner who is not an attendee, G11); 9 items covering
open/overdue/done/no-due/unassigned/ambiguous/orphaned. `FixedClock(2026-11-25)`.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M8-01 | seeded_db | `list` | Open + overdue items only. No done, no orphaned. Sorted due asc, NULLs last | REQ-LIST-02 |
| TC-M8-02 | seeded_db | `list --status overdue` | Only open items with due < 11-25 | REQ-LIST-01 |
| TC-M8-03 | seeded_db | `list --status done` | Only done items | REQ-LIST-01 |
| TC-M8-04 | seeded_db | `list --owner "Rahul"` | Only Rahul's items | REQ-LIST-01 |
| TC-M8-05 | seeded_db | `list --owner priya.nair@coditas.com` | Only Priya Nair's | REQ-LIST-01 |
| TC-M8-06 | seeded_db | `list --owner Priya` | stderr names both Priyas, exit 2, stdout empty | REQ-LIST-05 |
| TC-M8-07 | seeded_db | `list --owner Zed` | `no person matches`, exit 2 | REQ-LIST-05 |
| TC-M8-08 | seeded_db | `list --due-before 2026-11-22` | Only items with due < 11-22 | REQ-LIST-01 |
| TC-M8-09 | seeded_db | `list --due-before "not a date"` | exit 2, hint `YYYY-MM-DD` | REQ-LIST-01 |
| TC-M8-10 | seeded_db | `list --unassigned` | Items with no owner (incl. the ambiguous one) | REQ-LIST-01 |
| TC-M8-11 | seeded_db | `list --flag ambiguous_owner` | Only the ambiguous item | REQ-LIST-01 |
| TC-M8-12 | seeded_db | `list --flag orphaned` | The orphaned item shown | REQ-LIST-01 (G3) |
| TC-M8-13 | seeded_db | `list --owner Rahul --unassigned` | exit 2 | REQ-LIST-01 |
| TC-M8-14 | seeded_db, `--no-color` | `list` | Overdue rows contain `⚠ overdue`. Columns ID/Owner/Task/Due/Status/Src present | REQ-LIST-03 |
| TC-M8-15 | seeded_db, forced terminal colour | `list` | The overdue row has red ANSI styling | REQ-LIST-03 |
| TC-M8-16 | seeded_db | `list --json` | stdout parses as JSON, `schema_version == 1`, overdue status present, footer **not** on stdout | REQ-LIST-04 |
| TC-M8-17 | seeded_db | `list --json --status done` | `filters.status == "done"`, items consistent | REQ-LIST-04 |
| TC-M8-18 | Empty DB | `list` | stderr `No items match.`, exit 0 | REQ-LIST-02 |
| TC-M8-19 | seeded_db | `done <6-char id of open item>` | stdout `✓ …`, exit 0. Then `list --status done` includes it | REQ-DONE-01 |
| TC-M8-20 | seeded_db | `done <4-char unique prefix>` | Works | REQ-DONE-01 |
| TC-M8-21 | seeded_db | `done <id>` twice | Second: stderr `already done`, exit 0 | REQ-DONE-02 |
| TC-M8-22 | seeded_db with 2 ids sharing a prefix | `done <shared prefix>` | exit 2, both short ids in the hint | REQ-DONE-02 |
| TC-M8-23 | seeded_db | `done ffff` / `done ab` | exit 2 | REQ-DONE-02 |
| TC-M8-24 | seeded_db | `done <id>` | `done_source == 'cli'`, `done_at == clock.now()` in the DB | REQ-DONE-01 |
| TC-M8-25 | seeded_db | `list --owner vikram` | Vikram Rao's item (an owner with no `people` row) | REQ-LIST-01 (G11) |
