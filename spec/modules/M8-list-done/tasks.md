# M8 — Tasks

Branch: `feat/m8-list-done`

- [ ] **T8.1 `seeded_db` fixture** (built through the M6 repos, not raw SQL) in `tests/integration/conftest.py`.
- [ ] **T8.2 Write failing tests** TC-M8-01 … TC-M8-25.
- [ ] **T8.3 `resolve_owner_query`** (0 / 1 / many with candidate hint, item owners via `PeopleRepo.find`, G11). → TC-M8-04 … 07, 25
- [ ] **T8.4 `list_items` service**: filter building, `--due-before` parsing, contradiction checks, `ItemView` mapping, short ids.
      → TC-M8-01 … 03, 08 … 13
- [ ] **T8.5 Table renderer** (overdue style + marker, footer on stderr, empty message). → TC-M8-14, 15, 18
- [ ] **T8.6 JSON renderer** (schema v1, stdout only). → TC-M8-16, 17
- [ ] **T8.7 `done` command** (prefix resolution, mark, messages, exit codes). → TC-M8-19 … 24
- [ ] **T8.8 Replace the M0 stubs** with real commands, help text + examples.
- [ ] **T8.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR.
