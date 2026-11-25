# M10 — Tasks

Branch: `feat/m10-gmail-mcp`

- [ ] **T10.1 Fake MCP server fixtures** (FastMCP with recording tools + variants) and an in-memory `session_factory` in
      `tests/integration/mcp_fakes.py`.
- [ ] **T10.2 Write failing tests** TC-M10-01 … TC-M10-15.
- [ ] **T10.3 Adapter skeleton**: config validation, `ALLOWED_TOOLS`, guarded `_call`, only one public method. → TC-M10-03 … 05, 12
- [ ] **T10.4 Session handling**: stdio/http factories, initialize, `list_tools` check, schema arg validation, timeout wrapper,
      error mapping. → TC-M10-06, 07, 09 … 11
- [ ] **T10.5 Argument mapping + result parsing**. → TC-M10-01, 08, 13
- [ ] **T10.6 Safe logging**. → TC-M10-14
- [ ] **T10.7 `write_outbox`**. → TC-M10-15
- [ ] **T10.8 No-send regression test** across all tests (the session fixture asserts no forbidden calls at teardown). → TC-M10-02
- [ ] **T10.9 Quality gate**: ruff, mypy, coverage ≥ 80%. Update the status board, open the PR.
