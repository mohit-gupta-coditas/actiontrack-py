# actiontrack

Extract, track and follow up on action items from Markdown meeting notes. `actiontrack` reads checkbox lines such as
`- [ ] Priya to send the revised quote to Acme by Friday`, works out the owner and due date, merges duplicates across
meetings, and drafts follow-up emails in Gmail.

**It never sends email.** It only creates drafts, which you review and send yourself (see [No-send guarantee](#no-send-guarantee)).

The full specification is in [spec/requirements.md](spec/requirements.md).

## Install

Python 3.11 or later. Install it as an isolated tool:

```sh
uv tool install .        # or: pipx install .
actiontrack --version
```

For development:

```sh
uv sync
uv run actiontrack --help
```

## Quickstart

```sh
actiontrack ingest notes/                  # read every *.md note under notes/
actiontrack list                           # open items, overdue first
actiontrack done 17770a                    # mark one done (any unique prefix of 4+ chars)
actiontrack followup "Priya Shah" --dry-run   # preview the follow-up email
actiontrack followup "Priya Shah"             # create it as a Gmail draft
```

A note needs a meeting date and attendees. Both layouts work:

```markdown
# Meeting: Quote portal weekly
Date: 2026-09-08
Attendees: Priya Nair, Rahul Mehta <rahul.mehta@coditas.com>

## Action items
- [ ] Priya N. to send revised quote to Acme by Friday
- [x] Rahul to set up the staging environment
```

```markdown
---
title: Team standup
date: 2026-09-16
attendees: [Anita Desai, Lena Fischer]
---
- [ ] Lena to draft the case study outline by 2026-09-21
```

## Commands

Global options: `--db PATH`, `--config PATH`, `-v/-vv`, `-q`, `--no-color`, `--debug`, `--version`, `-h/--help`.
Every command's `--help` has examples.

### `ingest <folder>`

Reads every `*.md` note (recursively; `--no-recursive` for one level), extracts the action items and merges duplicates.
Unchanged files are skipped, so re-running is safe. Broken notes are listed and skipped, and the run carries on.

```console
$ actiontrack ingest notes/
Scanned 35 files: 30 ingested, 0 unchanged, 5 skipped, 0 removed
Items: 111 sources → 88 unique (23 exact merges, 0 fuzzy merges)
Flags: 6 unassigned, 5 ambiguous_owner, 5 owner_not_attendee, 1 multi_owner, 19 no_due, 4 unparsed_due
Skipped:
  notes/2026-09-09-notes-final-v2.md   empty_file: file is empty
  notes/2026-09-23-standup.md          missing_attendees: no attendees listed
  notes/2026-10-03-sales-pipeline.md   unparseable_date: cannot parse meeting date 'sometime last week'
  notes/scratch.md                     binary_file: file contains NUL bytes
  notes/untitled.md                    missing_date: no meeting date in frontmatter, Date: line or H1
```

Options: `--no-fuzzy` (exact merges only, for this run), `--report-json PATH` (the report as JSON).

### `list`

```console
$ actiontrack list --owner "Priya Shah"
┌────────┬────────────┬──────────────────────────────────────────┬────────────┬───────────┬─────┐
│ ID     │ Owner      │ Task                                     │ Due        │ Status    │ Src │
├────────┼────────────┼──────────────────────────────────────────┼────────────┼───────────┼─────┤
│ 17770a │ Priya Shah │ draft the test plan for invoice rounding │ 2026-09-11 │ ⚠ overdue │ 1   │
│ 267499 │ Priya Shah │ set up the test data                     │ —          │ open      │ 1   │
└────────┴────────────┴──────────────────────────────────────────┴────────────┴───────────┴─────┘
```

| Option | Meaning |
|---|---|
| `--owner TEXT` | Person key, email, full name or first name. An ambiguous first name lists the candidates (exit 2) |
| `--status open\|done\|overdue` | `open` (the default) includes overdue items |
| `--due-before DATE` | e.g. `2026-12-01` or `friday` |
| `--unassigned` | Items with no owner |
| `--flag NAME` | e.g. `ambiguous_owner`, `no_due`. Orphaned items (their note line was removed) show only with `--flag orphaned` |
| `--json` | Machine-readable output with a `schema_version`. stdout carries only the JSON |

Overdue rows are red **and** read `⚠ overdue`, so colour is never the only signal.

### `done <id>`

```console
$ actiontrack done 1777
✓ 17770a  draft the test plan for invoice rounding  (Priya Shah)
```

A done item stays done when its note is re-ingested.

### `followup <owner>`

Drafts one email to the owner listing their overdue and open items, each with its due date, source meeting and ID.
The recipient is the attendee's email, or `firstname.lastname@<email.domain>` derived from the full name.

```console
$ actiontrack followup "Priya Shah" --dry-run
Dry run: no draft created.
To: priya.shah@coditas.com
Subject: Follow-up: your open action items (2 open, 5 overdue)

Hi Priya,
...
```

Without `--dry-run` it creates the Gmail draft and prints its link. If the Gmail MCP server can't be reached, the
email is saved to the outbox folder (`<data dir>/outbox/*.eml`) and the command exits 3.

### `config show`

Prints each effective setting and where it came from (`flag`, `env`, `file` or `default`). `--json` is supported.

## Configuration

Precedence: command-line flags > environment variables > config file > defaults.

| Setting | Config file | Environment | Default |
|---|---|---|---|
| Database | `db_path` | `ACTIONTRACK_DB` (or `--db`) | `<data dir>/actiontrack.db` |
| Outbox folder | `outbox_dir` | — | `<data dir>/outbox` |
| Email domain | `[email] domain` | `ACTIONTRACK_EMAIL_DOMAIN` | `coditas.com` |
| Sign-off | `[email] sign_off` | — | `Thanks` |
| Fuzzy merging | `[dedup] fuzzy_enabled`, `fuzzy_threshold` | `ACTIONTRACK_FUZZY_THRESHOLD` | `true`, `88` |
| Numeric dates | `[parsing] date_order` | `ACTIONTRACK_DATE_ORDER` | `DMY` |
| "Today" (tests, demos) | — | `ACTIONTRACK_TODAY=2026-11-25` | the local date |

The config file is `config.toml` in the OS config folder (`%APPDATA%\actiontrack\` on Windows, `~/.config/actiontrack/`
on Linux, `~/Library/Application Support/actiontrack/` on macOS). The data dir is the OS data folder for `actiontrack`.

```toml
[email]
domain = "coditas.com"
sign_off = "Thanks,\nMohit"

[dedup]
fuzzy_threshold = 88
```

### Gmail MCP

`followup` creates drafts through a Gmail MCP server's `create_draft` tool. The CLI stores no Google credentials: point
it at an endpoint that is already authenticated, either a local stdio server or an HTTP URL.

```toml
[gmail_mcp]
transport = "stdio"                 # or "http"
command = "npx"                     # stdio: how to launch the server
args = ["-y", "<gmail-mcp-server>"]
# url = "http://localhost:8080/mcp" # http: the server URL
draft_tool = "create_draft"
to_as_list = true                   # the Gmail connector takes `to` as a list
# arg_names = { to = "to", subject = "subject", body = "body" }   # if the server names them differently
timeout_s = 30
```

Before calling the tool, `actiontrack` checks that the server lists `draft_tool` and that its input schema accepts the
arguments it sends.

#### Manual smoke test

Run this once with the real server configured, before a release:

1. Ingest notes in which you are an owner, then run `actiontrack followup "<your name>" --dry-run` and check the email.
2. Run `actiontrack followup "<your name>"`. It prints a draft link and exits 0.
3. In Gmail, open **Drafts**: the draft is there, addressed to you. Check **Sent**: nothing was sent.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, including an ingest that skipped broken notes, or output cut short by a closed pipe (`\| head`) |
| `1` | Fatal error (folder missing, database not writable) |
| `2` | User input error (unknown or ambiguous ID or owner, bad filter, bad config) |
| `3` | The Gmail MCP server failed. The email was saved to the outbox |
| `130` | Interrupted (Ctrl-C). The current database transaction is rolled back |

Errors are one short `Error:` line on stderr. `--debug` (or `ACTIONTRACK_DEBUG=1`) adds the Python traceback.

## No-send guarantee

- The MCP adapter exposes a single `create_draft(to, subject, body)` method. No generic tool call is reachable from the
  rest of the code.
- A hard-coded allowlist containing only `create_draft` is checked before every tool call. Any other tool name raises
  `ForbiddenToolError`.
- The tests run against fake servers that also offer `send_message`, `reply` and `forward`, and assert those are never called.

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest                     # fast tests
uv run pytest -m slow             # end-to-end and performance tests on notes/
uv run python scripts/trace_check.py
```

The work is spec-driven: see [spec/plan.md](spec/plan.md) for the modules, the status board and the decisions log.
