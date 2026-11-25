# M12 — Test Cases

Location: `tests/e2e/`. All `@pytest.mark.slow`. The CLI runs as a subprocess with `ACTIONTRACK_DB=<tmp>` and
`ACTIONTRACK_TODAY=2026-11-25` (unless stated). MCP uses the M10 fake server launched as a **stdio subprocess**
(`tests/e2e/fake_gmail_server.py`) that writes the calls it receives to a JSON file.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M12-01 | `notes/` | `ingest notes/` | Exit 0. stderr has no `Traceback`. The `Skipped:` section matches `expected.yaml.skipped` exactly (file + reason) | REQ-ACC-01 |
| TC-M12-02 | Ingested | `list --json` | Each `expected.duplicates` entry appears once with ≥ `min_sources` sources and due = the latest-meeting due date | REQ-ACC-02 |
| TC-M12-03 | Ingested | `list --flag ambiguous_owner --json` | Contains the items at each `expected.ambiguous` file:line. Their owner is null | REQ-ACC-03 |
| TC-M12-04 | Ingested | `list --unassigned --json` and `list --status overdue --json` | Unassigned is non-empty. No item with `due_date == null` in the overdue output | REQ-ACC-04 |
| TC-M12-05 | Fixture note dated 2026-11-18 with `- [ ] Rahul to send quote by Friday` added to a temp copy of notes/ | ingest + `list --json --owner Rahul` | That item has `due_date == "2026-11-20"` | REQ-ACC-05 |
| TC-M12-06 | Ingested | `list --status overdue` with `FORCE_COLOR=1` and without colour | Every row's due < today. Coloured: red ANSI. Plain: `⚠ overdue` | REQ-ACC-06 |
| TC-M12-07 | Ingested | `done <id>` → modify that item's note (touch the content) → `ingest` → `list --status done --json` | The item is still done | REQ-ACC-07 |
| TC-M12-08 | Ingested, fake MCP configured | `followup "<an owner with items>"` | Exactly 1 `create_draft` in the fake's call log, to the expected address. 0 send/reply/forward. Exit 0 | REQ-ACC-08, REQ-GEN-01 |
| TC-M12-09 | Ingested | `ingest notes/` again, compare `sqlite3 .dump` before/after (ignoring `ingested_at`) | Report shows 0 ingested. Dump identical | REQ-ACC-09 |
| TC-M12-10 | Ingested | `list --json` | `json.loads(stdout)` succeeds. stdout has no non-JSON line | REQ-ACC-10 |
| TC-M12-11 | — | `<cmd> --help` for every command. Then `done zz`, `list --owner Nobody`, `list --due-before junk`, `followup Nobody`, `ingest missing/` | Help: `Examples:` present. Errors: exit 1 or 2 as specified, `Error:` on stderr, no `Traceback` | REQ-ACC-11 |
| TC-M12-12 | Sample DB | Time `--help`, `list`, `done zzzz` (median of 5) | Each < 300 ms | REQ-CLI-08 |
| TC-M12-13 | `notes/` | Time `ingest` on a fresh DB | < 10 s hard fail (budget 5 s) | REQ-CLI-08 |
| TC-M12-14 | Built wheel | Install into a clean venv, run `actiontrack --version` | Exit 0, correct version | REQ-CLI-01 |
| TC-M12-15 | Repo | `python scripts/trace_check.py` | Exit 0. Every REQ ID is covered and has a single owner | traceability |
