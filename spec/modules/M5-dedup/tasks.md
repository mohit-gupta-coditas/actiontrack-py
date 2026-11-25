# M5 — Tasks

Branch: `feat/m5-dedup`. Can start right after M0 using hand-built `ParsedItem`s. It does not need M4 to be finished.

- [x] **T5.1 Write failing tests** TC-M5-01 … TC-M5-25, with the `src()` builder in `tests/unit/conftest.py`.
- [x] **T5.2 `normalize_task`**. → TC-M5-01, 02
- [x] **T5.3 `make_item_id`, `shortest_unique_prefixes`, `resolve_prefix`**. → TC-M5-19 … 23
- [x] **T5.4 Grouping loop**: deterministic order, exact pass, fuzzy pass against the canonical norm, injectable scorer, lazy rapidfuzz.
      → TC-M5-03 … 12, 25
- [x] **T5.5 Existing-item shells + orphan detection**. → TC-M5-16, 17
- [x] **T5.6 Merged-field rules** (due, status, flags, seen dates). → TC-M5-13 … 16
- [x] **T5.7 Decision log + determinism**. → TC-M5-18, 24
- [x] **T5.8 Quality gate**: ruff, mypy, coverage ≥ 90%. Update the status board, open the PR.
