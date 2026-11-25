# actiontrack — Requirements & Architecture Spec

| | |
|---|---|
| **Status** | Draft v1 |
| **Author** | Mohit Gupta |
| **Date** | 2026-11-25 |

---

## 1. Problem

Meeting notes pile up as markdown files. Action items get lost, and follow-up emails are written late or not at all.
`actiontrack` is a local CLI that reads meeting notes, tracks their action items in one store, and drafts follow-up
emails in Gmail for a person to review. **It never sends email.**

## 2. Goals / Non-goals

**Goals**
- Parse a folder of meeting notes (30+ files, some long and messy, some malformed) into structured action items.
- Track item status (open / done / overdue) across runs.
- Draft one follow-up email per owner as a Gmail draft, through the Gmail MCP connector.
- Never crash on bad input: skip it, report it, and continue.

**Non-goals**
- Sending email, scheduling sends, or any outbound message other than creating a draft.
- Writing changes back into the source markdown notes.
- LLM-generated content (emails are template-based and deterministic).
- Multi-user or server deployment. This is a single-user local tool.

## 3. Decisions Summary

| # | Topic | Decision |
|---|---|---|
| D1 | Language | Python 3.11+ |
| D2 | CLI framework | Typer (Click-based) |
| D3 | Storage | SQLite (stdlib `sqlite3`), one local DB file |
| D4 | Gmail integration | The CLI acts as an **MCP client** (Python `mcp` SDK) and calls the connector's `create_draft` tool |
| D5 | Email body | Deterministic Jinja2 template, no LLM |
| D6 | Relative date anchor | The **meeting date** of the note the item came from |
| D7 | Dedup | Normalized exact match first, then fuzzy match (same owner, `token_set_ratio ≥ 88`, configurable) |
| D8 | Dup due-date conflict | The **latest meeting wins**. Earlier due dates are kept in history |
| D9 | Same first name | Resolve against **that note's attendees list**. If still ambiguous, flag as `ambiguous_owner` |
| D10 | Missing owner / due | Store with `owner = NULL` (shown as *unassigned*) and/or `due_date = NULL`, plus flags |
| D11 | Malformed notes | Skip the whole note for: missing/unparseable date, missing attendees, broken frontmatter/encoding. Skip only the line for bad checkbox syntax |
| D12 | Re-ingest | Idempotent upsert keyed by file hash. CLI-set `done` is never reset |
| D13 | Recipient email | Use the attendee's email from the note if given, otherwise derive `firstname.lastname@coditas.com` |
| D14 | Item ID | Short content hash (git-style prefix, min 6 hex chars) |
| D15 | `list` output | Rich table (overdue highlighted) plus `--json` |
| D16 | Quality bar | pytest unit + integration tests, a mocked MCP server, ruff, mypy |

## 4. Input Format (Meeting Notes)

### 4.1 Expected structure

A note is accepted when it contains a **meeting date**, an **attendees list** and free-form body text.
Both of these layouts are supported:

**A. YAML frontmatter (preferred)**
```markdown
---
date: 2026-11-18
title: Q4 pricing sync
attendees:
  - Priya Shah <priya.shah@coditas.com>
  - Priya Nair
  - Rahul Mehta
---
## Notes
...free text...
- [ ] Priya Shah to send the revised quote by Friday
- [x] Rahul to book the venue
```

**B. Heading / inline fields (fallback)**
```markdown
# Q4 pricing sync — 2026-11-18
Attendees: Priya Shah, Priya Nair, Rahul Mehta
```

Meeting dates are parsed with `dateparser` using `STRICT_PARSING=True` and `DATE_ORDER=DMY` (team convention, configurable).
ISO `YYYY-MM-DD` is always tried first. The meeting date may come from: the frontmatter `date`, a `Date:` line, or a date in
the first H1 heading. If none of these exists, the note is malformed.

### 4.2 Action item lines

Recognised pattern (case-insensitive, leading whitespace allowed so nested lists work):

```
^\s*[-*+]\s*\[( |x|X)\]\s*(?P<body>.+)$
```

- `[ ]` → status `open`; `[x]`/`[X]` → status `done` (completed in the note itself).
- Lines that *look* like checkboxes but are malformed (`-[ ]`, `- []`, `- [ ]` with an empty body, `[ ] text` without a bullet)
  are **skipped with a line-level warning** (D11). The rest of the note is still processed.
- Checkboxes inside fenced code blocks are ignored.

## 5. Extraction Pipeline

Example input: `- [ ] Priya Shah to send the revised quote by Friday` in a note dated **Wed 2026-11-18**.

| Step | What it does | Result |
|---|---|---|
| 1. Detect | Checkbox regex (§4.2) | body = `Priya Shah to send the revised quote by Friday` |
| 2. Owner | Leading name before a connector (`to`, `will`, `should`, `needs to`, `:`, `—`), or an `@mention` anywhere | raw owner = `Priya Shah` |
| 3. Resolve owner | Match against this note's attendees (§6) | `Priya Shah` |
| 4. Due phrase | Trailing/inline phrase regex: `by/before/due/on/until <expr>`, `EOD`, `EOW`, `next week`, ISO dates, `12 Dec`, etc. | `by Friday` |
| 5. Resolve date | `dateparser` with `RELATIVE_BASE = meeting date` (D6) | `2026-11-20` |
| 6. Task | Body minus owner, connector and due phrase, then trimmed | `send the revised quote` |
| 7. Normalize | Lowercase, strip punctuation, collapse whitespace, drop stop-words (`the`, `a`, `an`) | `send revised quote` |

### 5.1 Date resolution rules
- A weekday name (`Friday`) resolves to the **next occurrence strictly after** the meeting date. *(Assumption: if a Friday
  meeting says "by Friday", that means the following week's Friday.)*
- `EOD` → the meeting date. `EOW` → the Friday of the meeting's week (or the next Friday if the meeting is on a Fri/Sat/Sun).
  `next week` → the Monday after.
- `end of month` → the last day of the meeting's month.
- If a due phrase is present but cannot be parsed, set `due_date = NULL`, set the flag `unparsed_due`, and keep the raw phrase in `due_raw`.

## 6. Owner Resolution (incl. same first name)

1. Build the attendee index for the note: `full_name`, `first_name`, `last_name`, `email` (if present).
2. Match the raw owner in this order:
   1. exact email, or an `@handle` matching the email local-part
   2. exact full name (case-insensitive)
   3. first name + last initial (`Priya S.`)
   4. first name only → **only if exactly one attendee has that first name**
3. If the first name alone matches more than one attendee (e.g. two Priyas) → `owner = NULL`, flag `ambiguous_owner`, and keep
   `owner_raw = "Priya"` and the candidate list. These items show up in `list --flag ambiguous_owner` for manual fixing.
4. If no name is detected → `owner = NULL`, flag `unassigned`.
5. A name that is not in the attendees list → stored as given, with the flag `owner_not_attendee`.
   *(Assumption: action items are sometimes assigned to people who were not in the meeting.)*

**Canonical person key** = lowercased email if known, otherwise `firstname.lastname` (D13). This key is used for dedup,
`--owner` filtering and `followup`.

## 7. Deduplication (D7, D8)

Run after parsing, per owner:

1. **Exact pass**: the same `owner_key` and an identical `task_norm` → same item.
2. **Fuzzy pass**: the same `owner_key` and `rapidfuzz.fuzz.token_set_ratio(task_norm_a, task_norm_b) ≥ threshold`
   (default **88**, config `dedup.fuzzy_threshold`, disabled with `--no-fuzzy`).
   - `token_set_ratio` ignores word order and extra words, so `send revised quote` and `send revised quote to client` score about 100.
   - Items with **no owner are never fuzzy-merged** (only exact matches), which avoids false merges of generic tasks.
3. When items are merged:
   - Every occurrence is kept in `item_sources` (file, line, meeting date, raw text, due date as written).
   - `due_date` = the due date from the **most recent meeting** that gave one. Earlier ones stay in the sources table.
   - `status`: once `done` (in a note or via the CLI), the item stays done. A later note showing `[ ]` again does not reopen it.
     *(Assumption. A `reopen` command is listed as future work.)*
   - `first_seen` = the earliest meeting date, and `last_seen` = the latest.
4. Each merge decision is logged with its score in the ingest report (verbose mode), so the threshold can be tuned.

## 8. Data Model (SQLite)

Default DB path: `<user_data_dir>/actiontrack.db` via `platformdirs` (§13.6). Override with `--db` or `ACTIONTRACK_DB`.

```sql
CREATE TABLE notes (
  path          TEXT PRIMARY KEY,
  sha256        TEXT NOT NULL,
  meeting_date  DATE,
  title         TEXT,
  ingested_at   TIMESTAMP NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok','skipped')),
  skip_reason   TEXT
);

CREATE TABLE people (
  key           TEXT PRIMARY KEY,   -- email lowercased
  full_name     TEXT NOT NULL,
  first_name    TEXT NOT NULL,
  email         TEXT NOT NULL
);

CREATE TABLE items (
  id            TEXT PRIMARY KEY,   -- full sha1 hex; CLI shows a short prefix
  owner_key     TEXT REFERENCES people(key),  -- NULL = unassigned/ambiguous
  owner_raw     TEXT,
  task          TEXT NOT NULL,      -- display text
  task_norm     TEXT NOT NULL,
  due_date      DATE,
  due_raw       TEXT,
  status        TEXT NOT NULL CHECK (status IN ('open','done')),
  done_source   TEXT CHECK (done_source IN ('note','cli')),
  done_at       TIMESTAMP,
  flags         TEXT NOT NULL DEFAULT '[]',   -- JSON array
  first_seen    DATE NOT NULL,
  last_seen     DATE NOT NULL
);

CREATE TABLE item_sources (
  item_id       TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  note_path     TEXT NOT NULL REFERENCES notes(path),
  line_no       INTEGER NOT NULL,
  raw_text      TEXT NOT NULL,
  meeting_date  DATE NOT NULL,
  due_date      DATE,
  PRIMARY KEY (item_id, note_path, line_no)
);

CREATE TABLE drafts (
  id            INTEGER PRIMARY KEY,
  owner_key     TEXT NOT NULL,
  gmail_draft_id TEXT,
  created_at    TIMESTAMP NOT NULL,
  item_ids      TEXT NOT NULL       -- JSON array
);
```

- **`overdue` is derived, not stored**: `status = 'open' AND due_date IS NOT NULL AND due_date < today`.
  Items with no due date are never overdue.
- Schema version is tracked with `PRAGMA user_version`, and migrations are applied on startup.

### 8.1 Item ID (D14)
- `id = sha1(owner_key or "∅" + "|" + task_norm)` for the first item of a dedup group. Fuzzy-merged items keep the ID of the
  group's first-seen item.
- The CLI shows the first **6** hex chars. `done` accepts any unique prefix of 4 or more chars. An ambiguous prefix is an error
  that lists the candidates.
- IDs are stable across re-ingest and a DB rebuild, as long as the canonical text does not change.

## 9. Commands

Global options: `--db PATH`, `--config PATH`, `-v/--verbose` (repeatable), `-q/--quiet`, `--no-color`, `--debug`, `--version`, `-h/--help`.
Extra command: `actiontrack config show` (§13.6).

### 9.1 `actiontrack ingest <folder>`
- Recursively finds `*.md` files (non-recursive with `--no-recursive`).
- For each file, if the `sha256` is unchanged since the last ingest it is skipped (D12). Otherwise the file is parsed, and its old
  `item_sources` rows are removed and re-inserted.
- Items whose only sources were removed (e.g. the line was deleted from the note) are marked with the flag `orphaned`, not deleted.
- Never resets `status='done'` where `done_source='cli'`.
- All writes for one run happen in a single transaction per file, so a failure on one file does not corrupt the others.
- **Ingest report** (stdout, plus `--report-json PATH`):
  ```
  Scanned 34 files: 29 ingested, 2 unchanged, 3 skipped
  Items: 112 found → 87 unique (19 exact merges, 6 fuzzy merges)
  Flags: 5 unassigned, 2 ambiguous_owner, 4 no_due, 1 unparsed_due
  Skipped:
    notes/2026-10-03-standup.md   missing meeting date
    notes/broken.md                invalid YAML frontmatter (line 4)
    notes/retro-old.md             not valid UTF-8
  Line warnings:
    notes/2026-11-02-sync.md:41    malformed checkbox "-[ ] Rahul ..."
  ```
- Exit code `0` even when some notes are skipped. `1` only on fatal errors (folder missing, DB not writable).

### 9.2 `actiontrack list`
| Option | Meaning |
|---|---|
| `--owner TEXT` | Matches the person key, email, full name, or first name. An ambiguous first name prints the candidates and exits 2 |
| `--status open\|done\|overdue` | `overdue` ⊂ `open` |
| `--due-before DATE` | Any date `dateparser` understands, relative to today (e.g. `2026-12-01`, `next friday`) |
| `--unassigned` | Only items with `owner_key IS NULL` |
| `--flag NAME` | e.g. `ambiguous_owner`, `orphaned` |
| `--json` | Machine-readable output |

- The default view shows all open items sorted by due date (nulls last), then owner.
- Table columns: `ID`, `Owner`, `Task`, `Due`, `Status`, `Sources` (count). **Overdue rows are shown in red**, with a `⚠` marker
  when colour is off.

### 9.3 `actiontrack done <id>`
- Resolves the ID prefix (§8.1) and sets `status='done'`, `done_source='cli'`, `done_at=now`.
- Already done → prints a notice and exits 0. Unknown or ambiguous ID → exits 2.

### 9.4 `actiontrack followup <owner>`
1. Resolves the owner (same rules as `--owner`). An ambiguous or unknown owner → error, no draft.
2. Selects that owner's **open + overdue** items. If there are none → message, no draft.
3. Resolves the recipient (D13):
   - the email from any attendees entry for this person, **or**
   - `firstname.lastname@coditas.com`, derived from the full name (lowercased, accents removed, spaces/hyphens in multi-part
     names joined with `.`, e.g. `Anna Maria Lopez` → `anna.maria.lopez@coditas.com`). *(Assumption about multi-part names; confirm.)*
   - Only a first name known → error `cannot derive email: no last name for "Priya"`.
   - The domain comes from config (`email.domain`, default `coditas.com`).
4. Renders the email from a Jinja2 template (`templates/followup.md.j2`):
   - Subject: `Follow-up: your open action items (N open, M overdue)`
   - Body: greeting, an **Overdue** section and then an **Open** section, each item with its task, due date and source meeting
     (title + date), and a sign-off.
5. `--dry-run` prints the rendered email and does not call MCP.
6. Otherwise it calls the Gmail MCP `create_draft` tool and prints the draft ID/link, then records a row in `drafts`.
7. **It never sends** (see §10.2).

## 10. Gmail MCP Integration (D4)

### 10.1 Client
- Uses the official Python `mcp` SDK (`ClientSession`) over the transport set in config:
  ```toml
  [gmail_mcp]
  transport = "stdio"            # or "http"
  command   = "npx"              # stdio: server launch command
  args      = ["-y", "<gmail-mcp-server>"]
  url       = ""                 # http: server URL
  draft_tool = "create_draft"
  ```
- Auth/OAuth is handled by the MCP server. The CLI stores no Google credentials.
- Before calling the tool, the client checks that `draft_tool` is in `list_tools()` and fails with a clear message if it is not.
- Timeout of 30 s. On a connection failure the rendered email is saved to `<user_data_dir>/outbox/<owner>-<ts>.eml` so the work
  is not lost, and the command exits 3.

### 10.2 No-send guarantee
- The MCP adapter exposes **only** a `create_draft(to, subject, body)` method. No generic `call_tool` is available to the
  rest of the code.
- A hard-coded **allowlist** `{"create_draft"}` is checked before every `call_tool`, and any other tool name raises
  `ForbiddenToolError`.
- Tests assert that `send_message`, `reply` and `forward` are never invoked (§14).

## 11. Architecture

```
actiontrack/
├── __main__.py          # python -m actiontrack
├── cli.py               # Typer app; argument parsing and output only
├── config.py            # TOML config + env overrides
├── models.py            # shared dataclasses passed between modules (contracts)
├── errors.py            # typed errors + ExitCode
├── clock.py             # Clock protocol, SystemClock, FixedClock
├── console.py           # stdout/stderr consoles, logging setup
├── parsing/
│   ├── note_loader.py   # read file, encoding check, frontmatter/heading → NoteMeta
│   ├── items.py         # checkbox detection, owner/due/task extraction
│   ├── dates.py         # relative date resolution anchored on meeting date
│   └── people.py        # attendee parsing, owner resolution, email derivation
├── dedup.py             # normalize + exact/fuzzy grouping
├── store/
│   ├── db.py            # connection, migrations
│   └── repo.py          # ItemRepo, NoteRepo, PeopleRepo
├── services/
│   ├── ingest.py        # orchestrates loader → parser → dedup → repo; builds report
│   ├── query.py         # list filters, overdue derivation
│   └── followup.py      # select items, render template, call DraftSink
├── email/
│   ├── render.py        # Jinja2 rendering
│   └── gmail_mcp.py     # MCP client adapter (allowlisted create_draft only)
└── templates/followup.md.j2
```

**Layering rules**
- `cli` → `services` → (`parsing`, `dedup`, `store`, `email`). Nothing imports `cli`.
- `parsing` and `dedup` are **pure** (no I/O apart from reading the given file, no DB), which keeps them unit-testable.
- `services/followup.py` depends on a `DraftSink` protocol, and `gmail_mcp.py` implements it. Tests inject a fake.

**Data flow (ingest)**
```
folder → [note_loader] → NoteMeta + lines ──(malformed? → SkipRecord)
       → [items] → RawItem[] ──(bad line? → LineWarning)
       → [people] owner resolution → [dates] due resolution
       → [dedup] groups → [repo] upsert (txn per file) → IngestReport
```

**Key dependencies**: `typer`, `rich`, `platformdirs`, `python-frontmatter` (or `pyyaml`), `dateparser`, `rapidfuzz`, `jinja2`, `mcp`.

## 12. Error Handling Rules

| Situation | Behaviour |
|---|---|
| Empty file / not UTF-8 / binary | Skip the note, reason in the report |
| Invalid YAML frontmatter | Skip the note, reason + line in the report |
| No meeting date | Skip the note (relative dates can't be resolved) |
| No attendees | Skip the note |
| Malformed checkbox line | Skip the line, warning with `file:line` |
| Unparseable due phrase | Keep the item, `due_date=NULL`, flag `unparsed_due` |
| Unexpected exception in one note | Caught at the per-file boundary, reported as `internal error: <type>`, ingest continues |
| DB locked / not writable | Fatal, exit 1 |

Exit codes: `0` ok, `1` fatal, `2` user input error (bad ID/owner/filter), `3` external (MCP) failure, `130` interrupted (Ctrl-C).

## 13. CLI Best Practices

The tool follows widely accepted CLI conventions (see [clig.dev](https://clig.dev)). These are requirements, not suggestions.

### 13.1 Packaging & installation
- Packaged with `pyproject.toml` (PEP 621) and a `[project.scripts] actiontrack = "actiontrack.cli:app"` entry point.
  `python -m actiontrack` also works (`__main__.py`).
- Installable as an isolated tool: `pipx install .` / `uv tool install .`. Dependencies are locked (`uv.lock`) for reproducible builds.
- Semantic versioning. `actiontrack --version` prints the version and exits 0.

### 13.2 Command design
- Use a consistent `actiontrack <verb> [args] [--options]` pattern, with positional args only for the main object (`<folder>`, `<id>`, `<owner>`).
- Every flag has a long form, and common ones also have a short form (`-v`, `-q`, `-h`). Flag names are the same in every command
  (`--owner` means the same thing everywhere).
- The tool works fully non-interactively. It never blocks on a prompt, so it can be scripted and used in CI.
- Commands are idempotent where possible (`ingest`, `done`), so re-running them is always safe.
- The outward-facing action (`followup`) supports `--dry-run`, and prints exactly what was drafted and to whom.

### 13.3 Help & discoverability
- `-h/--help` on the app and on every command. Each command's help has a one-line summary, a description, and **at least one example**.
- If you run `actiontrack` with no command, it shows short usage plus the list of commands, not a stack trace.
- Shell completion is available through Typer (`--install-completion` / `--show-completion`) for bash, zsh, fish and PowerShell.
- A mistyped command suggests the closest match ("Did you mean `list`?").

### 13.4 Output
- **stdout is for data, stderr is for everything else** (progress, warnings, errors, the ingest summary when `--json` is used).
  This keeps `actiontrack list --json | jq …` clean.
- Output for people (rich tables, colour) only when stdout is a TTY. Plain output when piped.
- Respect `NO_COLOR` and `--no-color`. Colour is never the only signal (overdue also gets the `⚠` marker).
- `--json` output has a documented, stable schema with a `"schema_version"` field. Breaking changes bump it.
- `-q/--quiet` suppresses everything except data and errors. `-v` / `-vv` increase the log level (INFO / DEBUG), and logs go to stderr.
- Progress bar for `ingest` on stderr, only on a TTY.
- On Windows, stdout/stderr are reconfigured to UTF-8 so names with accents and the `⚠` marker print correctly.

### 13.5 Errors
- Errors are short, written for people, and say what to do next, e.g.
  `Error: ID "a3f" matches 2 items (a3f91c, a3f0d2). Use more characters.`
- No Python traceback by default. `--debug` (or `ACTIONTRACK_DEBUG=1`) shows the full traceback.
- Exit codes are fixed and documented (§12). Typer/Click usage errors use exit 2.
- Ctrl-C rolls back the current DB transaction, prints `Interrupted`, and exits 130.

### 13.6 Configuration precedence
`command-line flags` > `environment variables (ACTIONTRACK_*)` > `config file` > `built-in defaults`.
- File locations come from `platformdirs` (OS-native, not hard-coded):
  - config: `user_config_dir("actiontrack")/config.toml` (e.g. `%APPDATA%\actiontrack\config.toml` on Windows, `~/.config/actiontrack/` on Linux)
  - data (DB, outbox): `user_data_dir("actiontrack")`
- `actiontrack config show` prints the effective config and where each value came from (useful for debugging).
- Secrets are never stored by the CLI (MCP server auth is handled by the server).

### 13.7 Performance
- `list`, `done` and `--help` start in under 300 ms. Heavy imports (`dateparser`, `rapidfuzz`, `mcp`, `jinja2`) are
  **imported lazily** inside the commands that need them.
- `ingest` streams files one at a time and does not load the whole folder into memory. The SQLite indexes used are
  `items(owner_key)`, `items(status, due_date)` and `item_sources(note_path)`.

### 13.8 Robustness & portability
- `pathlib` everywhere. No shell-specific paths, and works on Windows, macOS and Linux.
- Files are read as UTF-8, with BOM handling and `\r\n` line endings normalized.
- SQLite uses WAL mode and a busy timeout, so a second instance waits instead of failing immediately.
- Dates are timezone-aware for "today", using the local timezone (overridable with `ACTIONTRACK_TODAY` for tests and demos).

### 13.9 Code structure for the CLI layer
- `cli.py` contains only argument parsing, output formatting and the mapping from exceptions to exit codes. All logic lives in `services/`.
- Domain errors are typed exceptions (`UserInputError`, `ExternalServiceError`, `ForbiddenToolError`) that the CLI maps to exit codes in one place.
- A `README.md` with installation steps, a quickstart, and an example for each command.

## 14. Testing & Quality (D16)

- **Unit** (pytest): checkbox regex; owner extraction (connectors, `@mentions`, two Priyas); date resolution (weekday on the same
  weekday, EOW, month end, year rollover from a December meeting); normalization; exact/fuzzy dedup including the
  near-miss cases (`update doc` vs `update docs page`); email derivation; ID prefix resolution.
- **Fixtures**: small hand-written notes for each edge case under `tests/fixtures/`.
- **Integration**: `ingest` on the provided `notes/` sample folder (30+ files) with snapshot assertions on the report: count of
  skipped files, the expected malformed files listed, unique item count. Re-running ingest is idempotent (same DB state).
- **CLI**: `typer.testing.CliRunner` for every command and exit code.
- **MCP**: a fake in-process MCP server that exposes `create_draft`, `send_message`, `reply` and `forward`. Tests assert that only
  `create_draft` is called, and that a direct attempt to call another tool raises `ForbiddenToolError`.
- **Static**: `ruff` (lint + format) and `mypy --strict` on the `actiontrack` package.
- **Time**: "today" is injected through a `Clock` so overdue tests are deterministic.

## 15. Configuration

`<user_config_dir>/config.toml` (see §13.6; all keys optional):
```toml
[email]
domain = "coditas.com"
sign_off = "Thanks,\nMohit"

[dedup]
fuzzy_threshold = 88
fuzzy_enabled = true

[gmail_mcp]
transport = "stdio"
command = "..."
args = []
```

## 16. Acceptance Criteria

1. `ingest notes/` completes on the sample folder with no unhandled exception, and lists every deliberately malformed file as skipped with a reason.
2. An item repeated across meetings appears **once** in `list`, with a source count > 1 and the latest due date.
3. `- [ ] Priya to …` in a note with two Priyas is flagged `ambiguous_owner` and is not assigned to either one.
4. Items with no owner/no due are listed (`--unassigned`) and never counted as overdue.
5. `by Friday` in a note dated Wed 2026-11-18 is stored as `2026-11-20`.
6. `list --status overdue` shows only open items whose due date is before today, highlighted.
7. `done <prefix>` marks the item done, and re-running `ingest` does not reopen it.
8. `followup "Priya Shah"` creates exactly one Gmail draft to `priya.shah@coditas.com` containing that person's open and overdue items, and **no send tool is ever invoked**.
9. Running `ingest` twice in a row reports all files unchanged and makes no DB changes.
10. `actiontrack list --json | python -m json.tool` succeeds: there are no warnings or progress output on stdout.
11. Every command's `--help` includes an example, and no user error produces a Python traceback unless `--debug` is set.

## 17. Open Questions / Assumptions to Confirm

| # | Item | Current assumption |
|---|---|---|
| Q1 | Weekday on the same day ("by Friday" said on a Friday) | The following week's Friday |
| Q2 | A note re-lists a CLI-done item as `[ ]` | It stays done (future: `reopen <id>`) |
| Q3 | Owner not in the attendees list | Kept, flagged `owner_not_attendee`. Email derived from the full name if available |
| Q4 | Multi-part / hyphenated surnames in email derivation | Parts joined with `.`, accents removed |
| Q5 | Does `followup` also include items with `ambiguous_owner` whose candidates include this person? | No, they are excluded until resolved |
| Q6 | Which Gmail MCP server is used (exact launch command / URL) | Configurable. It must expose `create_draft(to, subject, body)` |
| Q7 | Multiple owners on one line ("Priya and Rahul to …") | The first owner is kept. Flag `multi_owner` |
| Q8 | Non-ISO dates like `03/04/2026` | Read day-first (3 April). Configurable |

## 18. Requirement Index

Stable IDs for traceability. Module specs under `spec/modules/` reference these IDs, and each ID is owned by exactly one module (see `spec/plan.md`).

| ID | Requirement | Source |
|---|---|---|
| REQ-GEN-01 | The tool never sends email. Only drafts are created | §2, §10.2 |
| REQ-GEN-02 | Bad input never crashes the tool: skip, report, continue | §2, §12 |
| REQ-GEN-03 | Source notes are read-only. The tool never writes to them | §2 |
| REQ-NOTE-01 | Accept the YAML frontmatter note layout | §4.1 A |
| REQ-NOTE-02 | Accept the heading / inline-field note layout | §4.1 B |
| REQ-NOTE-03 | Meeting date from frontmatter, `Date:` line or H1. ISO first, then strict DMY | §4.1 |
| REQ-NOTE-04 | Skip a note with a missing or unparseable meeting date | §4.1, D11 |
| REQ-NOTE-05 | Skip a note with no attendees | D11 |
| REQ-NOTE-06 | Skip a note with broken frontmatter, invalid encoding, an empty file or binary content | D11, §12 |
| REQ-NOTE-07 | Handle UTF-8 BOM and CRLF/CR line endings | §13.8 |
| REQ-ITEM-01 | Detect checkbox lines. `[ ]` → open, `[x]` → done | §4.2 |
| REQ-ITEM-02 | Skip malformed checkbox lines with a line-level warning | §4.2, D11 |
| REQ-ITEM-03 | Ignore checkboxes inside fenced code blocks | §4.2 |
| REQ-ITEM-04 | Extract the owner via connector words or `@mention` | §5 |
| REQ-ITEM-05 | The task is the body minus owner, connector and due phrase | §5 |
| REQ-ITEM-06 | Several owners on one line → the first is kept, flag `multi_owner` | Q7 |
| REQ-ITEM-07 | No owner → flag `unassigned`. No due phrase → flag `no_due` | D10 |
| REQ-DATE-01 | Detect the due phrase (`by/before/due/on/until …`, EOD, EOW, ISO, `12 Dec`) | §5 |
| REQ-DATE-02 | Resolve relative due dates against the meeting date | D6 |
| REQ-DATE-03 | A weekday name resolves to the next occurrence strictly after the meeting date | §5.1, Q1 |
| REQ-DATE-04 | EOD / EOW / next week / end of month rules | §5.1 |
| REQ-DATE-05 | Unparseable due phrase → `due_date` NULL, flag `unparsed_due`, keep `due_raw` | §5.1 |
| REQ-DATE-06 | Numeric non-ISO dates are read day-first (configurable) | Q8 |
| REQ-PEOPLE-01 | Parse attendees as a name with an optional email | §4.1, §6 |
| REQ-PEOPLE-02 | Owner match order: email/handle → full name → first name + initial → unique first name | §6 |
| REQ-PEOPLE-03 | An ambiguous first name → no owner, flag `ambiguous_owner`, candidates kept | §6, D9 |
| REQ-PEOPLE-04 | An owner not in the attendees is kept with the flag `owner_not_attendee` | §6, Q3 |
| REQ-PEOPLE-05 | Canonical person key (lowercased email) | §6 |
| REQ-PEOPLE-06 | Email derivation `firstname.lastname@<domain>`, accents stripped, multi-part names | D13, Q4 |
| REQ-DEDUP-01 | Task normalization | §5 |
| REQ-DEDUP-02 | Exact pass: same owner + same normalized task | §7 |
| REQ-DEDUP-03 | Fuzzy pass: same owner, `token_set_ratio ≥ threshold`. Configurable, `--no-fuzzy` | §7 |
| REQ-DEDUP-04 | Items with no owner are never fuzzy-merged | §7 |
| REQ-DEDUP-05 | Merge rules: all sources kept, latest due wins, done is sticky, first/last seen | §7, D8 |
| REQ-DEDUP-06 | Merge decisions are logged with their score | §7 |
| REQ-ID-01 | Content-hash item IDs that stay the same across re-ingest and rebuild | §8.1 |
| REQ-ID-02 | 6-char display. Any unique prefix of 4+ chars accepted. Ambiguity is an error | §8.1 |
| REQ-STORE-01 | SQLite schema | §8 |
| REQ-STORE-02 | Overdue is derived, never stored | §8 |
| REQ-STORE-03 | Migrations via `PRAGMA user_version` | §8 |
| REQ-STORE-04 | DB path from platformdirs, overridable with `--db` / `ACTIONTRACK_DB` | §8, §13.6 |
| REQ-STORE-05 | WAL mode + busy timeout | §13.8 |
| REQ-STORE-06 | Indexes for the main queries | §13.7 |
| REQ-INGEST-01 | Recursive `*.md` scan, `--no-recursive` | §9.1 |
| REQ-INGEST-02 | Unchanged files (same sha256) are skipped | §9.1, D12 |
| REQ-INGEST-03 | A changed file has its sources replaced | §9.1 |
| REQ-INGEST-04 | Items that lose all their sources are flagged `orphaned`, never deleted | §9.1 |
| REQ-INGEST-05 | A CLI-set `done` is never reset by ingest | §9.1, D12 |
| REQ-INGEST-06 | One transaction per file. A failure in one file doesn't affect the others | §9.1, §12 |
| REQ-INGEST-07 | Ingest report: text on stdout plus `--report-json` | §9.1 |
| REQ-INGEST-08 | Ingest exits 0 when files are skipped, 1 on fatal errors | §9.1 |
| REQ-INGEST-09 | Progress bar on stderr, TTY only | §13.4 |
| REQ-LIST-01 | Filters: `--owner`, `--status`, `--due-before`, `--unassigned`, `--flag` | §9.2 |
| REQ-LIST-02 | Default view and sort order | §9.2 |
| REQ-LIST-03 | Table columns, overdue in red + `⚠` | §9.2 |
| REQ-LIST-04 | `--json` with `schema_version` | §9.2, §13.4 |
| REQ-LIST-05 | An ambiguous `--owner` prints the candidates and exits 2 | §9.2 |
| REQ-DONE-01 | `done <prefix>` marks the item done (`done_source=cli`) | §9.3 |
| REQ-DONE-02 | Already done → notice, exit 0. Unknown/ambiguous → exit 2 | §9.3 |
| REQ-FU-01 | Followup resolves the owner. Ambiguous/unknown → error, no draft | §9.4 |
| REQ-FU-02 | Select open + overdue items. None → no draft | §9.4 |
| REQ-FU-03 | Recipient: the attendee's email or a derived one. First name only → error | §9.4, D13 |
| REQ-FU-04 | Deterministic template: subject plus overdue and open sections | §9.4, D5 |
| REQ-FU-05 | `--dry-run` prints the email and makes no MCP call | §9.4 |
| REQ-FU-06 | Create the draft, print its ID/link, record it in `drafts` | §9.4 |
| REQ-MCP-01 | MCP client over stdio or HTTP, from config | §10.1 |
| REQ-MCP-02 | Check the draft tool exists via `list_tools()` | §10.1 |
| REQ-MCP-03 | Only `create_draft` is exposed. Allowlist → `ForbiddenToolError` | §10.2 |
| REQ-MCP-04 | 30 s timeout. On failure write the outbox `.eml` and exit 3 | §10.1 |
| REQ-MCP-05 | The CLI stores no credentials | §10.1, §13.6 |
| REQ-CLI-01 | Packaging, entry point, `python -m`, `--version` | §13.1 |
| REQ-CLI-02 | Help with examples, usage when no args, completion, typo suggestions | §13.3 |
| REQ-CLI-03 | stdout for data, stderr for everything else | §13.4 |
| REQ-CLI-04 | TTY-aware colour, `NO_COLOR`, `--no-color`, `-q`, `-v/-vv` | §13.4 |
| REQ-CLI-05 | Readable errors. Traceback only with `--debug` | §13.5 |
| REQ-CLI-06 | Exit codes 0/1/2/3/130. Ctrl-C rolls back | §12, §13.5 |
| REQ-CLI-07 | Config precedence, platformdirs locations, `config show` | §13.6 |
| REQ-CLI-08 | `list`/`done`/`--help` start in < 300 ms (lazy imports) | §13.7 |
| REQ-CLI-09 | Portable paths, UTF-8 output on Windows | §13.4, §13.8 |
| REQ-CLI-10 | An injectable `Clock`. `ACTIONTRACK_TODAY` override | §13.8, §14 |
| REQ-ACC-01..11 | Acceptance criteria 1–11 | §16 |

## 19. Future Work
- `reopen <id>` and `assign <id> <owner>` commands (to fix ambiguous/unassigned items).
- A `people.yaml` override for aliases/nicknames.
- Optional LLM polish of the email body.
- A watch mode that re-ingests when files change.
