# M6 — Tasks

Branch: `feat/m6-store`

- [ ] **T6.1 Write failing tests** TC-M6-01 … TC-M6-21, with builders for `ParsedItem` / `ItemGroup` in `tests/integration/conftest.py`.
- [ ] **T6.2 `connect`, pragmas, `transaction`, error mapping**. → TC-M6-04, 05, 07, 21
- [ ] **T6.3 Migration runner + `0001_init.sql`**. → TC-M6-01 … 03, 06
- [ ] **T6.4 `NoteRepo` + `SourceRepo`** (JSON columns, round trip). → TC-M6-08, 09
- [ ] **T6.5 `PeopleRepo`**. → TC-M6-10, 11
- [ ] **T6.6 `ItemRepo.apply_groups` / `existing` / orphan flagging**. → TC-M6-15, 16
- [ ] **T6.7 `ItemRepo.query`** (filters, derived overdue, order) **+ `mark_done`, `get`, `ids`**. → TC-M6-12 … 14, 17 … 19
- [ ] **T6.8 `DraftRepo`**. → TC-M6-20
- [ ] **T6.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR. Raise G1/G2 for root spec confirmation.
