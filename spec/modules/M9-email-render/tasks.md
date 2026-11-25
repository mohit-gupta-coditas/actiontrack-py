# M9 — Tasks

Branch: `feat/m9-email-render`

- [ ] **T9.1 Write failing tests** TC-M9-01 … TC-M9-14. Write the expected snapshot files **by hand** from the spec (not generated).
- [ ] **T9.2 `followup.txt.j2`** template + package data included in the wheel (hatchling ships every file under `actiontrack/`; check the built wheel).
- [ ] **T9.3 `render_followup`**: sorting, days overdue, subject rules, Jinja env settings, lazy import, overdue validation. → TC-M9-01 … 09, 13
- [ ] **T9.4 Determinism / whitespace / injection safety**. → TC-M9-10 … 12, 14
- [ ] **T9.5 Quality gate**: ruff, mypy, coverage ≥ 90%. Update the status board, open the PR.
