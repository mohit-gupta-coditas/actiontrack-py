# M0 — Tasks

Branch: `feat/m0-foundation`

- [x] **T0.1 Project scaffold**: `pyproject.toml` (deps, scripts, ruff/mypy/pytest config), `actiontrack/__init__.py`,
      `__main__.py`, `tests/` tree, `.gitignore`, `.python-version`. `uv sync` works.
      *Done when:* `uv run pytest` runs (0 tests) and `uv run actiontrack` is importable.
- [x] **T0.2 Write failing tests** TC-M0-01 … TC-M0-27 in `tests/unit/core/`. Mark them xfail-strict only where they depend on later
      tasks of this module, so that nothing passes by accident.
- [x] **T0.3 `errors.py`**: `ExitCode` and the error hierarchy. → TC-M0-12, 14, 16 (partly)
- [x] **T0.4 `clock.py`**: `Clock`, `SystemClock`, `FixedClock`, `clock_from_env`. → TC-M0-17, 18
- [x] **T0.5 `models.py`**: all contracts from spec §8, including `IngestReport.to_json`. → TC-M0-25, 26
- [x] **T0.6 `config.py`**: dataclasses, `default_paths`, `load_config` with precedence and validation, source tracking.
      → TC-M0-06 … 10
- [x] **T0.7 `console.py`**: `Output`, `make_output`, UTF-8 reconfigure, logging setup, info/warn/error helpers. → TC-M0-19 … 22, 24
- [x] **T0.8 `cli.py` skeleton**: global callback, `AppContext`, stub commands with help/examples, no-args usage,
      typo suggestion, `--version`. → TC-M0-01 … 05, 27
- [x] **T0.9 `main()` error boundary**: exception → exit-code mapping, `--debug` / `ACTIONTRACK_DEBUG`, KeyboardInterrupt.
      → TC-M0-12 … 16
- [x] **T0.10 `config show`** (table + `--json`). → TC-M0-11
- [x] **T0.11 Lazy-import guard**: check the import graph. → TC-M0-23
- [x] **T0.12 Quality gate**: ruff, `mypy --strict`, coverage ≥ 80%. Update the `plan.md` status board, open the PR.
