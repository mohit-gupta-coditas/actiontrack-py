# M0 — Foundation

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | — |
| **Files** | `pyproject.toml`, `actiontrack/__init__.py`, `__main__.py`, `cli.py` (skeleton), `config.py`, `models.py`, `errors.py`, `clock.py`, `console.py` |
| **REQ IDs** | REQ-CLI-01, 02, 03, 04, 05, 06, 07, 09, 10 |

## 1. Purpose
Provide the skeleton that every other module plugs into: packaging, the Typer app with its global options, error-to-exit-code
mapping, configuration, output consoles, the injectable clock, and the **shared data contracts** (`models.py`) that let
M1–M11 be built in parallel.

## 2. Packaging (REQ-CLI-01)
- `pyproject.toml` (PEP 621, build backend `hatchling`), `requires-python = ">=3.11"`.
- `[project.scripts] actiontrack = "actiontrack.cli:main"`.
- Runtime deps: `typer`, `rich`, `platformdirs`, `pyyaml`, `dateparser`, `rapidfuzz`, `jinja2`, `mcp`.
  Dev deps: `pytest`, `pytest-cov`, `ruff`, `mypy`, `types-PyYAML`.
- `actiontrack/__init__.py` exposes `__version__` (single source, read by hatch).
- `python -m actiontrack` calls `cli.main()`.
- The tool config lives in `pyproject.toml`: ruff (line length 100, rule sets `E,F,I,B,UP,SIM,RUF`), mypy strict, pytest
  (`-m "not slow"` by default, `testpaths = ["tests"]`).

## 3. Errors and exit codes (REQ-CLI-05, REQ-CLI-06) — `errors.py`

```python
class ExitCode(IntEnum):
    OK = 0
    FATAL = 1
    USER = 2
    EXTERNAL = 3
    INTERRUPTED = 130

class ActionTrackError(Exception):
    exit_code: ClassVar[ExitCode] = ExitCode.FATAL
    def __init__(self, message: str, *, hint: str | None = None) -> None: ...

class FatalError(ActionTrackError): ...                      # exit 1
class UserInputError(ActionTrackError): exit_code = USER     # exit 2
class ExternalServiceError(ActionTrackError): exit_code = EXTERNAL   # exit 3
class ForbiddenToolError(ActionTrackError): ...               # exit 1 — programming error, must never happen
```

## 4. Clock (REQ-CLI-10) — `clock.py`

```python
class Clock(Protocol):
    def today(self) -> date: ...
    def now(self) -> datetime: ...            # timezone-aware, local tz

class SystemClock: ...
class FixedClock:                             # tests + ACTIONTRACK_TODAY
    def __init__(self, today: date, now: datetime | None = None) -> None: ...

def clock_from_env(env: Mapping[str, str]) -> Clock
    # ACTIONTRACK_TODAY=YYYY-MM-DD → FixedClock; invalid value → UserInputError
```

## 5. Configuration (REQ-CLI-07) — `config.py`

```python
@dataclass(frozen=True)
class McpConfig:
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    draft_tool: str = "create_draft"
    arg_names: Mapping[str, str] = {"to": "to", "subject": "subject", "body": "body"}
    to_as_list: bool = True       # the Gmail connector's shape (G20)
    timeout_s: float = 30.0

@dataclass(frozen=True)
class Config:
    db_path: Path
    outbox_dir: Path
    email_domain: str = "coditas.com"
    sign_off: str = "Thanks"
    fuzzy_enabled: bool = True
    fuzzy_threshold: int = 88            # 0..100
    date_order: Literal["DMY", "MDY"] = "DMY"
    gmail_mcp: McpConfig = McpConfig()
    sources: Mapping[str, Literal["flag", "env", "file", "default"]]   # where each key came from

def default_paths() -> tuple[Path, Path, Path]     # (config_file, db_path, outbox_dir) via platformdirs
def load_config(*, flags: Mapping[str, Any], env: Mapping[str, str], config_path: Path | None) -> Config
```

- **Precedence**: flags > env (`ACTIONTRACK_DB`, `ACTIONTRACK_EMAIL_DOMAIN`, `ACTIONTRACK_FUZZY_THRESHOLD`,
  `ACTIONTRACK_DATE_ORDER`) > TOML file > defaults.
- File: `platformdirs.user_config_dir("actiontrack")/config.toml`, read with `tomllib`. A missing default file is fine.
  A missing file passed explicitly via `--config` is a `UserInputError`.
- Invalid values (threshold outside 0–100, unknown date order, malformed TOML) → `UserInputError` that names the key and source.
- TOML layout as in root spec §15 (`[email]`, `[dedup]`, `[gmail_mcp]`, plus `[parsing] date_order`).
  `db_path` and `outbox_dir` are top-level keys. Unknown keys under `[gmail_mcp]` are a `UserInputError`.
- `settings_view(config) -> dict[str, tuple[value, source]]` feeds `config show`.

## 6. Console and logging (REQ-CLI-03, REQ-CLI-04, REQ-CLI-09) — `console.py`

```python
@dataclass
class Output:
    out: rich.console.Console     # stdout — data only
    err: rich.console.Console     # stderr — messages, warnings, progress, logs
    quiet: bool
    verbosity: int                # 0 WARNING, 1 INFO, 2+ DEBUG

def make_output(*, no_color: bool, quiet: bool, verbosity: int, env: Mapping[str, str]) -> Output
def configure_stdio_utf8() -> None     # sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")
```
- Colour is used only if the stream is a TTY **and** `NO_COLOR` is not set **and** `--no-color` is not passed.
- `FORCE_COLOR` (rich) forces colour on a non-TTY. With it set, the consoles are built with `legacy_windows=False`, so forced colour
  is ANSI on Windows too instead of Win32 console calls that a pipe drops (G35).
- `logging` is configured to write to `Output.err` at the level set by verbosity. `-q` forces ERROR.
- The helpers `info()`, `warn()` and `error()` are methods on `Output` and all write to stderr. `warn` and `info` are
  suppressed by `-q`. `Output.data(text)` writes unwrapped plain text to stdout (for JSON).

## 7. CLI skeleton (REQ-CLI-02, REQ-CLI-05, REQ-CLI-06) — `cli.py`

- A `typer.Typer` app with a global callback holding the options: `--db`, `--config`, `-v/--verbose` (count), `-q/--quiet`,
  `--no-color`, `--debug`, `--version` (eager), `-h/--help`.
- The callback builds an `AppContext(config, output, clock, debug)` and stores it in `ctx.obj`.
- With no command: prints usage and the command list to stdout, exit 0.
- Commands `ingest`, `list`, `done` and `followup` are **registered as stubs** that raise `FatalError("not implemented")`.
  M7, M8 and M11 replace them. `config show` is implemented here.
- Every command's help text has a one-line summary, a description and an `Examples:` block.
- Typo suggestion: an unknown command → `Error: No such command 'lst'. Did you mean 'list'?` (difflib, cutoff 0.6), exit 2.
- `create_app() -> Typer` builds the app (tests build their own to register throwaway commands); `app = create_app()`.
- `run(argv=None, *, app_=None, env=None) -> int` holds the error boundary below and returns the exit code;
  `main()` = `configure_stdio_utf8()` + `sys.exit(run())`. The boundary:
  - `ActionTrackError` → `Error: <message>` (+ `Hint: <hint>`) on stderr, `exit(e.exit_code)`.
  - `KeyboardInterrupt` → `Interrupted` on stderr, exit 130.
  - stdout closed by its reader (rich's broken-pipe hook, `BrokenPipeError`, or on Windows an `OSError` after which stdout can't
    be flushed) → stdout is pointed at `os.devnull`, nothing is printed, exit 0 (G36).
  - Any other `Exception` → `Error: internal error (<TypeName>). Re-run with --debug for details.`, exit 1.
  - `--debug` / `ACTIONTRACK_DEBUG=1` → also print the full traceback to stderr.
- `config show` prints each effective key, its value and its source (`flag/env/file/default`). `--json` is supported.
- **Lazy imports**: `cli.py` and everything it imports at module level must not import `dateparser`, `rapidfuzz`, `mcp` or `jinja2`
  (they are imported inside command functions). This supports REQ-CLI-08 (verified in M12).
- Shell completion: Typer's built-in `--install-completion` / `--show-completion` stay enabled.

## 8. Shared data contracts — `models.py`

All are `@dataclass(frozen=True, slots=True)`. Dates are `datetime.date`, paths are `pathlib.Path`.

```python
class Flag(StrEnum):
    UNASSIGNED = "unassigned"; AMBIGUOUS_OWNER = "ambiguous_owner"; OWNER_NOT_ATTENDEE = "owner_not_attendee"
    MULTI_OWNER = "multi_owner"; NO_DUE = "no_due"; UNPARSED_DUE = "unparsed_due"; ORPHANED = "orphaned"

class SkipReason(StrEnum):
    EMPTY_FILE = "empty_file"; BINARY_FILE = "binary_file"; INVALID_ENCODING = "invalid_encoding"
    INVALID_FRONTMATTER = "invalid_frontmatter"; MISSING_DATE = "missing_date"; UNPARSEABLE_DATE = "unparseable_date"
    MISSING_ATTENDEES = "missing_attendees"; READ_ERROR = "read_error"; INTERNAL_ERROR = "internal_error"

class WarningCode(StrEnum):
    MALFORMED_CHECKBOX = "malformed_checkbox"; EMPTY_TASK = "empty_task"

class NoteMeta:            # M1 output
    path: Path; sha256: str; meeting_date: date; title: str | None
    attendees_raw: tuple[str, ...]
    lines: tuple[tuple[int, str], ...]      # (1-based line number in file, text) of the body, LF-normalized

class SkipRecord:          # M1 / M7 output
    path: Path; reason: SkipReason; detail: str; line_no: int | None = None

class LineWarning:         # M4 output
    path: Path; line_no: int; code: WarningCode; text: str

class Attendee:            # M2
    full_name: str; first_name: str; last_name: str | None
    email: str | None          # explicit email from the note
    key: str                   # explicit email lowercased | derived email | "name:<first>" (G1)
    derived_email: str | None  # firstname.lastname@domain, None if no last name

class OwnerResolution:     # M2
    owner_key: str | None; owner_display: str | None; owner_raw: str | None
    flags: frozenset[Flag]; candidates: tuple[str, ...]   # candidate keys if ambiguous

class DueResolution:       # M3
    due_date: date | None; due_raw: str | None; flags: frozenset[Flag]
    span: tuple[int, int] | None          # char span of the due phrase in the input text

class ParsedItem:          # M4 output; one per checkbox occurrence ("source")
    note_path: Path; line_no: int; raw_text: str; meeting_date: date; note_title: str | None
    owner: OwnerResolution; task: str; due: DueResolution
    checked: bool                       # [x] in note
    flags: frozenset[Flag]              # owner.flags | due.flags | item-level flags

class ExistingItem:        # M6 → M5
    id: str; owner_key: str | None; task_norms: frozenset[str]
    status: Literal["open", "done"]; done_source: Literal["note", "cli"] | None; done_at: datetime | None

class MergeDecision:       # M5
    item_id: str; kind: Literal["exact", "fuzzy"]; score: float
    source: tuple[Path, int]; matched_task_norm: str

class ItemGroup:           # M5 output → M6
    id: str; owner_key: str | None; owner_display: str | None; owner_raw: str | None
    task: str; task_norm: str; due_date: date | None; due_raw: str | None
    status: Literal["open", "done"]; done_source: Literal["note", "cli"] | None; done_at: datetime | None
    flags: frozenset[Flag]; first_seen: date; last_seen: date
    sources: tuple[ParsedItem, ...]

class Person:              # M6 row
    key: str; full_name: str; first_name: str; email: str | None

class IngestReport:        # M7
    scanned: int; ingested: int; unchanged: int; removed: int
    skipped: tuple[SkipRecord, ...]; warnings: tuple[LineWarning, ...]
    sources_total: int; items_total: int; exact_merges: int; fuzzy_merges: int
    flag_counts: Mapping[Flag, int]; decisions: tuple[MergeDecision, ...]
    def to_json(self) -> dict[str, Any]
```

`to_json()` adds `"schema_version": JSON_SCHEMA_VERSION` (1). The generic `to_jsonable(value)` converts any contract:
enums → values, dates → ISO, paths → POSIX strings, frozensets → sorted lists.

## 9. Out of scope
Business logic for any command; DB schema (M6); MCP (M10).

## 10. Open questions
None.
