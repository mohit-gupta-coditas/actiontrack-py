# M7 — Tasks

Branch: `feat/m7-ingest`

- [ ] **T7.1 Fixtures**: build `tests/fixtures/notes/ingest_basic/` as described in tests.md (including one fuzzy-duplicate pair and one
      exact-duplicate pair across notes).
- [ ] **T7.2 Write failing tests** TC-M7-01 … TC-M7-19.
- [ ] **T7.3 Scanner** (recursive flag, suffix filter, hidden dirs, sort, resolve). → TC-M7-01 … 03
- [ ] **T7.4 Per-file pipeline** with hash skip, a transaction per file, and the exception boundary. → TC-M7-04, 05, 10, 11, 19
- [ ] **T7.5 Deleted-file handling** under the root. → TC-M7-07, 08
- [ ] **T7.6 Regroup step** (M5 + `apply_groups`), with `--no-fuzzy` override. → TC-M7-06, 09, 18
- [ ] **T7.7 Report builder** + text renderer + `--report-json` + `-q` / `-v` variants. → TC-M7-12 … 15
- [ ] **T7.8 CLI command** replacing the M0 stub: help text with examples, progress sink (rich, stderr, TTY only), exit codes.
      → TC-M7-16, 17
- [ ] **T7.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR.
