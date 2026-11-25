# M12 — Tasks

Branch: `feat/m12-e2e-release`

- [ ] **T12.1 Add the sample `notes/` folder** to the repo (provided by the user).
- [ ] **T12.2 Manual review of the notes** → write `tests/e2e/expected.yaml` (skipped files + reasons, known duplicates, ambiguous lines).
      Done by reading the notes, **not** by running the tool.
- [ ] **T12.3 Fake stdio Gmail MCP server** `tests/e2e/fake_gmail_server.py` (reuse the M10 tool definitions, log calls to a file).
- [ ] **T12.4 Write the e2e tests** TC-M12-01 … TC-M12-11 (subprocess harness helper `run_cli(*args, env=…)`).
- [ ] **T12.5 Fix any defects found.** Each fix goes back to its module's spec/tests first (add a TC there), then the code.
- [ ] **T12.6 Performance tests** TC-M12-12, 13. If they fail, profile and fix lazy-import leaks.
- [ ] **T12.7 `scripts/trace_check.py`**. → TC-M12-15
- [ ] **T12.8 `README.md`** (install, config, Gmail MCP setup, an example per command, exit codes, no-send guarantee).
- [ ] **T12.9 CI workflow** (matrix, lint, types, tests, slow tests on ubuntu, trace check) + wheel smoke test. → TC-M12-14
- [ ] **T12.10 Manual Gmail smoke test** with the real MCP server (needs Q6 answered). Record the result in the PR.
- [ ] **T12.11 Final gate**: all acceptance criteria green. Every module is ✅ on the plan status board. Tag `v0.1.0`.
