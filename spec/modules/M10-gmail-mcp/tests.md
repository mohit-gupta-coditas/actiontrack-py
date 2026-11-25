# M10 — Test Cases

Location: `tests/integration/test_gmail_mcp.py`. **Fake server**: an in-process `mcp.server.fastmcp.FastMCP` exposing `create_draft`,
`send_message`, `reply` and `forward`, each recording its calls into a shared list. It is connected through memory streams with a test
`session_factory`. A variant fake has no `create_draft`, and another returns `isError`, sleeps, or uses different argument names.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M10-01 | Fake server | `create_draft(to, subject, body)` | `create_draft` called once with the mapped args. `DraftResult.draft_id` parsed | REQ-MCP-01, REQ-GEN-01 |
| TC-M10-02 | Fake server, any sequence of adapter use | — | The recorded calls never contain `send_message`, `reply` or `forward` | REQ-GEN-01, REQ-MCP-03 |
| TC-M10-03 | Adapter instance | `adapter._call("send_message", {...})` | `ForbiddenToolError`. The fake records no call | REQ-MCP-03 |
| TC-M10-04 | `McpConfig(draft_tool="send_message")` | construct the adapter | `ForbiddenToolError` | REQ-MCP-03 |
| TC-M10-05 | `GmailMcpDraftSink` class | inspect public attributes | Only `create_draft` is public and callable (no `call_tool`, `send`, …) | REQ-MCP-03 |
| TC-M10-06 | Fake without `create_draft` | `create_draft` | `ExternalServiceError` "does not expose" | REQ-MCP-02 |
| TC-M10-07 | Fake whose tool expects `recipients` instead of `to` | `create_draft` with default arg_names | `ExternalServiceError` listing the expected/actual names | REQ-MCP-02 (G8) |
| TC-M10-08 | Same fake, `arg_names.to="recipients"`, `to_as_list=True` | `create_draft` | Succeeds. The fake received `recipients == ["x@…"]` | REQ-MCP-01 (G8) |
| TC-M10-09 | Fake returning `isError=True` | `create_draft` | `ExternalServiceError` with the server's text | REQ-MCP-04 |
| TC-M10-10 | Fake that sleeps 2 s, `timeout_s=0.5` | `create_draft` | `ExternalServiceError` (timeout) in < 1.5 s | REQ-MCP-04 |
| TC-M10-11 | stdio transport with `command="does-not-exist-xyz"` | `create_draft` | `ExternalServiceError` (launch failure) | REQ-MCP-04 |
| TC-M10-12 | stdio transport with no `command` | construct | `UserInputError` naming `gmail_mcp.command` | REQ-MCP-01 |
| TC-M10-13 | Result forms: structuredContent `{id}`, text JSON `{"draftId":…}`, plain text | parse | id, id, None | REQ-MCP-01 |
| TC-M10-14 | `-vv` logging captured | `create_draft` | Logs contain the tool name and arg keys. They don't contain the recipient, subject or body values | REQ-MCP-05 |
| TC-M10-15 | — | `write_outbox` twice with the same timestamp | Two files (`…eml`, `…-2.eml`). Parsed back with `email.parser`: To/Subject/body match, the status header present | REQ-MCP-04 |
