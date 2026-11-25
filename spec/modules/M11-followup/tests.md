# M11 — Test Cases

Location: `tests/integration/test_followup.py` and `tests/integration/test_cli_followup.py`. Uses `seeded_db` (from M8) and a
`RecordingSink` (a fake `DraftSink`) or the M10 fake MCP server for the end-to-end case. `FixedClock(2026-11-25)`.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M11-01 | Rahul has 2 open + 1 overdue item | `followup Rahul` | Exactly 1 `create_draft` call, to `rahul.mehta@coditas.com`, subject `(2 open, 1 overdue)`, the body lists 3 items. Exit 0 | REQ-FU-02, 03, 06 |
| TC-M11-02 | Same | `followup Rahul` | `drafts` row recorded with the 3 item ids. stdout has `Draft created`. stderr has `never sends` | REQ-FU-06 |
| TC-M11-03 | Two Priyas | `followup Priya` | exit 2, both candidates listed, sink factory not called | REQ-FU-01 |
| TC-M11-04 | — | `followup Nobody` | exit 2, sink not called | REQ-FU-01 |
| TC-M11-05 | Person whose items are all done | `followup <them>` | stderr `No open items`, exit 0, sink not called | REQ-FU-02 |
| TC-M11-06 | Person with an orphaned open item + 1 normal open item | `followup` | The email has 1 item only | REQ-FU-02 (G3) |
| TC-M11-07 | Person with an explicit email `p.s@client.com` | `followup` | Draft to `p.s@client.com` (not the derived one) | REQ-FU-03 |
| TC-M11-08 | Person stored as `name:priya` (first name only), with items | `followup priya` (unique) | `cannot derive email: no last name for "Priya"`, exit 2, sink not called | REQ-FU-03 |
| TC-M11-09 | Rahul as in 01 | `followup Rahul --dry-run` | stdout starts `To: rahul.mehta@coditas.com`, then Subject, then the body. Sink factory **never called**. No `drafts` row. Exit 0 | REQ-FU-05 |
| TC-M11-10 | Sink raising `ExternalServiceError("timeout")` | `followup Rahul` | exit 3. An outbox `.eml` exists with the same subject/body. stderr mentions the path. No `drafts` row | REQ-FU-06, REQ-MCP-04 |
| TC-M11-11 | Rahul as in 01 | `followup Rahul` | Item statuses unchanged afterwards | REQ-FU-06 |
| TC-M11-12 | **End-to-end with the M10 fake MCP server** (real `GmailMcpDraftSink`) | `followup Rahul` | The fake recorded exactly 1 `create_draft`, 0 `send_message`/`reply`/`forward` | REQ-FU-06, REQ-GEN-01 |
| TC-M11-13 | `followup "Priya Nair"` with two Priyas | `followup` | Resolves uniquely, draft to `priya.nair@coditas.com` | REQ-FU-01 |
| TC-M11-14 | An `ambiguous_owner` item whose candidates include Priya Shah | `followup "Priya Shah"` | The email does not list it (Q5) | REQ-FU-02 |
| TC-M11-15 | Rahul as in 01 | `followup Rahul` | Each item is tagged `[<short id>]` with the same prefix `list` prints (G23) | REQ-FU-04 |
| TC-M11-16 | Sink returning a `DraftResult` with no ID and no link | `followup Rahul` | Exit 0, `drafts` row with `gmail_draft_id` NULL, stdout says no draft ID was returned (G24) | REQ-FU-06 |
| TC-M11-17 | `[gmail_mcp] transport = "http"` with no `url` (real factory) | `followup Rahul` | Exit 2, `gmail_mcp.url is not set`, no outbox file, no `drafts` row (G25) | REQ-FU-06 |
| TC-M11-18 | The `drafts` insert fails after the sink returned a draft | `followup Rahul` | Exit 1, the error names the draft link, exactly 1 `create_draft` call, no outbox (G26) | REQ-FU-06 |
