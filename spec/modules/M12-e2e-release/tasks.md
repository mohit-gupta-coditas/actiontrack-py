# M12 — Tasks

Branch: `feat/m12-e2e-release`

- [x] **T12.1 Add the sample `notes/` folder** to the repo (provided by the user).
- [x] **T12.2 Manual review of the notes** → write `tests/e2e/expected.yaml` (skipped files + reasons, known duplicates, ambiguous lines).
      Done by reading the notes, **not** by running the tool.
- [x] **T12.3 Fake stdio Gmail MCP server** `tests/e2e/fake_gmail_server.py` (reuse the M10 tool definitions, log calls to a file).
- [x] **T12.4 Write the e2e tests** TC-M12-01 … TC-M12-11 (subprocess harness helper `run_cli(*args, env=…)`).
- [x] **T12.5 Fix any defects found.** Found and fixed: G35 (forced colour on Windows, M0), G36 (closed stdout, M0), G37 (H1 title label, M1). Each fix goes back to its module's spec/tests first (add a TC there), then the code.
- [x] **T12.6 Performance tests** TC-M12-12, 13. If they fail, profile and fix lazy-import leaks. No leak: no heavy library is imported by
      `--help`/`list`/`done`. TC-M12-12 runs on Linux only (§4); CI measures it.
- [x] **T12.7 `scripts/trace_check.py`**. → TC-M12-15
- [x] **T12.8 `README.md`** (install, config, Gmail MCP setup, an example per command, exit codes, no-send guarantee).
- [x] **T12.9 CI workflow** (matrix, lint, types, tests, slow tests on ubuntu, trace check) + wheel smoke test. → TC-M12-14
- [x] **T12.10 Manual Gmail smoke test** with the real MCP server (Q6). Steps in the README. Done by the user; record the result in the PR (G29). The user approved the release on 2026-11-26.
- [x] **T12.11 Final gate**: all acceptance criteria green. Every module is ✅ on the plan status board. Tag `v0.1.0` only after T12.10 is confirmed (G29). Tagged `v0.1.0` on f519d52 (2026-11-26).
