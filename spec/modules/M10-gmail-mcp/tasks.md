# M10 — Tasks

Branch: `feat/m10-gmail-mcp`

- [x] **T10.1 Fake MCP server fixtures** (low-level `mcp.server.Server` with recording tools + variants) and an in-memory `session_factory` in
      `tests/integration/mcp_fakes.py`.
- [x] **T10.2 Write failing tests** TC-M10-01 … TC-M10-18.
- [x] **T10.3 Adapter skeleton**: config validation, `ALLOWED_TOOLS`, guarded `_call`, only one public method. → TC-M10-03 … 05, 12
- [x] **T10.4 Session handling**: stdio/http factories, initialize, `list_tools` check, schema arg validation, timeout wrapper,
      error mapping, `list_tools` pagination, `required` check. → TC-M10-06, 07, 09 … 11, 17, 18
- [x] **T10.5 Argument mapping + result parsing**. → TC-M10-01, 08, 13
- [x] **T10.6 Safe logging**. → TC-M10-14
- [x] **T10.7 `write_outbox`**. → TC-M10-15, 16
- [x] **T10.8 No-send regression test** across all tests (the session fixture asserts no forbidden calls at teardown). → TC-M10-02
- [x] **T10.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR.
