# M1 — Tasks

Branch: `feat/m1-note-loader`

- [ ] **T1.1 Fixtures**: create `tests/fixtures/notes/loader/` with one file per scenario. Byte-level cases are generated in tests.
- [ ] **T1.2 Write failing tests** TC-M1-01 … TC-M1-24.
- [ ] **T1.3 Read / empty / binary / decode / normalize / hash** (steps 1–6). → TC-M1-15 … 19, 22, 23
- [ ] **T1.4 Frontmatter split + YAML errors with file line numbers**. → TC-M1-12 … 14, 20, 21
- [ ] **T1.5 `parse_meeting_date`** (ISO fast path, strict dateparser, lazy import). → TC-M1-05, 06, 09
- [ ] **T1.6 Meeting date sources** (frontmatter → `Date:` line → H1) + title derivation. → TC-M1-01 … 03, 07, 08
- [ ] **T1.7 Attendee sources** (frontmatter list/string → inline line → heading list). → TC-M1-01, 02, 04, 10, 11
- [ ] **T1.8 Performance check** on a large note. → TC-M1-24
- [ ] **T1.9 Quality gate**: ruff, mypy, coverage ≥ 90%. Update the status board, open the PR.
