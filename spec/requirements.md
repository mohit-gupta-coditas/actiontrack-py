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
├── cli.py               # Typer app; argument parsing and output only
├── config.py            # TOML config + env overrides
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

## 18. Future Work
- `reopen <id>` and `assign <id> <owner>` commands (to fix ambiguous/unassigned items).
- A `people.yaml` override for aliases/nicknames.
- Optional LLM polish of the email body.
- A watch mode that re-ingests when files change.
