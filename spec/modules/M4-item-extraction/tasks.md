# M4 — Tasks

Branch: `feat/m4-item-extraction`

- [x] **T4.1 Write failing tests** TC-M4-01 … TC-M4-23 (`NoteMeta` + `Roster` test builders in `tests/unit/parsing/conftest.py`).
- [x] **T4.2 `classify_line`** with valid/malformed patterns and fence tracking. → TC-M4-01 … 10, 23
- [x] **T4.3 `clean_inline_markdown`**. → TC-M4-18
- [x] **T4.4 `split_owner`** (leading name + connectors, uppercase guard, multi-owner, `@mention` fallback). → TC-M4-11 … 17
- [x] **T4.5 Due integration + task assembly** (span removal, trimming, empty task warning). → TC-M4-01, 13, 19, 21
- [x] **T4.6 `extract_items`** wiring (roster resolve, flag union, ordering). → TC-M4-15, 20, 22
- [x] **T4.7 Quality gate**: ruff, mypy, coverage ≥ 90%. Update the status board, open the PR.
