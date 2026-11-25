# M11 — Tasks

Branch: `feat/m11-followup`

- [ ] **T11.1 `RecordingSink` test double** + extend `seeded_db` with the cases needed (explicit email, `name:` person, orphaned item).
- [ ] **T11.2 Write failing tests** TC-M11-01 … TC-M11-13.
- [ ] **T11.3 Owner + item selection** (reuse M8 `resolve_owner_query`, ItemFilter, exclusions). → TC-M11-03 … 06, 13
- [ ] **T11.4 Recipient resolution**. → TC-M11-07, 08
- [ ] **T11.5 EmailItem mapping + render call**. → TC-M11-01
- [ ] **T11.6 Dry-run path** (the factory is not invoked). → TC-M11-09
- [ ] **T11.7 Draft path**: sink call, DraftRepo record, messages, outbox fallback, exit 3. → TC-M11-02, 10, 11
- [ ] **T11.8 CLI command** replacing the M0 stub (help + examples) and wiring the real `GmailMcpDraftSink`. → TC-M11-12
- [ ] **T11.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR.
