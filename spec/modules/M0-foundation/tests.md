# M0 — Test Cases

Location: `tests/unit/core/` (CLI tests use `typer.testing.CliRunner` with `mix_stderr=False`).

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M0-01 | Package installed | `actiontrack --version` | stdout = `actiontrack <__version__>`, exit 0 | REQ-CLI-01 |
| TC-M0-02 | Package installed | `python -m actiontrack --version` (subprocess) | Same output as TC-01 | REQ-CLI-01 |
| TC-M0-03 | — | `actiontrack` with no args | Usage and the 4 commands + `config` listed on stdout, exit 0 | REQ-CLI-02 |
| TC-M0-04 | — | `<cmd> --help` for `ingest`, `list`, `done`, `followup`, `config show` | Each output contains `Examples:` and at least one `actiontrack <cmd>` line | REQ-CLI-02 |
| TC-M0-05 | — | `actiontrack lst` | stderr contains `Did you mean 'list'?`, exit 2 | REQ-CLI-02 |
| TC-M0-06 | A default exists, the file sets threshold 80, env sets 85, flag absent | `load_config` | threshold 85, source `env` | REQ-CLI-07 |
| TC-M0-07 | File sets `db_path`, `--db` flag given | `load_config` | flag value wins, source `flag` | REQ-CLI-07 |
| TC-M0-08 | No config file at the default path | `load_config` | All defaults. Paths under the platformdirs dirs (monkeypatched) | REQ-CLI-07 |
| TC-M0-09 | `--config missing.toml` | any command | `Error:` on stderr naming the path, exit 2 | REQ-CLI-07, REQ-CLI-05 |
| TC-M0-10 | TOML with `fuzzy_threshold = 150` | `load_config` | `UserInputError` mentioning `fuzzy_threshold` and the file | REQ-CLI-07 |
| TC-M0-11 | Env sets the domain | `config show --json` | JSON on stdout, `email_domain.source == "env"`, nothing else on stdout | REQ-CLI-07, REQ-CLI-03 |
| TC-M0-12 | A command raising `UserInputError("bad", hint="try x")` | invoke | stderr `Error: bad` + `Hint: try x`, no `Traceback`, exit 2 | REQ-CLI-05, REQ-CLI-06 |
| TC-M0-13 | Same as 12 with `--debug` | invoke | stderr contains `Traceback`, exit 2 | REQ-CLI-05 |
| TC-M0-14 | A command raising `ExternalServiceError` | invoke | exit 3 | REQ-CLI-06 |
| TC-M0-15 | A command raising `KeyboardInterrupt` | invoke | stderr `Interrupted`, exit 130 | REQ-CLI-06 |
| TC-M0-16 | A command raising `ValueError` | invoke | stderr `internal error (ValueError)`, exit 1, no traceback | REQ-CLI-05, REQ-CLI-06 |
| TC-M0-17 | `ACTIONTRACK_TODAY=2026-11-18` | `clock_from_env` | `FixedClock`, `today() == date(2026,11,18)` | REQ-CLI-10 |
| TC-M0-18 | `ACTIONTRACK_TODAY=18th-ish` | `clock_from_env` | `UserInputError` | REQ-CLI-10 |
| TC-M0-19 | `NO_COLOR=1`, forced terminal | `make_output` then print styled text | No ANSI escape codes in the output | REQ-CLI-04 |
| TC-M0-20 | Non-TTY stream | `make_output` | Colour disabled | REQ-CLI-04 |
| TC-M0-21 | `-q` | `warn("x")`, `info("y")`, `error("z")` | Only `z` on stderr | REQ-CLI-04 |
| TC-M0-22 | `-vv` | logging at DEBUG | DEBUG record appears on stderr, stdout empty | REQ-CLI-03, REQ-CLI-04 |
| TC-M0-23 | Fresh interpreter (subprocess) | `import actiontrack.cli` | None of `dateparser`, `rapidfuzz`, `mcp`, `jinja2` is in `sys.modules` | REQ-CLI-08 (enabler) |
| TC-M0-24 | stdout wrapped with cp1252 encoding | `configure_stdio_utf8()` then print `⚠ Pérez` | No `UnicodeEncodeError` | REQ-CLI-09 |
| TC-M0-25 | Each dataclass in `models.py` | try to set an attribute | `FrozenInstanceError` | contracts |
| TC-M0-26 | `IngestReport` built with sample data | `to_json()` → `json.dumps` | Serializes; flags/reasons as strings, dates ISO | contracts |
| TC-M0-27 | Stub command `ingest` (before M7) | invoke | `Error: not implemented`, exit 1. Retired with M11: no stub is left | REQ-CLI-06 |
| TC-M0-28 | Non-TTY stdout, `FORCE_COLOR=1`, legacy Windows console detected | `make_output`, print `[red]x[/red]` | ANSI `[31m` in the output (G35) | REQ-CLI-04 |
| TC-M0-29 | A command whose stdout reader has gone (rich's broken-pipe hook, or a Windows `OSError` with stdout unflushable). Also a bare `BrokenPipeError` | `run` | Exit 0, nothing on stderr (G36). The bare `BrokenPipeError` is Typer's: `SystemExit(1)`, nothing on stderr | REQ-CLI-06 |
