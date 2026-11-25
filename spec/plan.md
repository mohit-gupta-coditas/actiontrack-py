# actiontrack — Implementation Plan (Spec-Driven Development)

| | |
|---|---|
| **Root spec** | [requirements.md](requirements.md). This is the source of truth, and module specs are derived from it |
| **Status** | In progress. M0–M11 done |
| **Date** | 2026-11-25 |

---

## 1. How we work

Every module goes through the same steps, in this order:

1. **Spec**: `modules/<M>/spec.md` is reviewed and marked *Approved*. Any change to the root spec is made there first.
2. **Tests (red)**: every test case in `modules/<M>/tests.md` is written as a pytest test whose name contains its TC ID
   (e.g. `test_TC_M3_04_weekday_same_day_rolls_to_next_week`). They all fail.
3. **Implement (green)**: work through `modules/<M>/tasks.md` in order, ticking tasks off as they pass.
4. **Gate**: the module's Definition of Done (below) passes. Update the status board in §4.
5. **Merge**: branch `feat/<m-id>-<name>` → PR → `main`. The PR description links the module spec and lists its TC IDs.

### Definition of Done (every module)
- All TCs in the module's `tests.md` are implemented and passing.
- `ruff check`, `ruff format --check` and `mypy --strict actiontrack` are clean.
- Line coverage of the module's package is ≥ 90% for the pure modules (M1–M5, M9), and ≥ 80% for the others.
- No public interface differs from the spec. If it had to, the spec was updated first (in the same PR).
- Every REQ ID the module owns appears in at least one TC.

### Conventions
- **IDs**: requirements `REQ-<AREA>-NN` (root spec §18) · modules `M0`–`M12` · tasks `T<m>.<n>` · test cases `TC-M<m>-NN`.
- **Test locations**: `tests/unit/<package>/` for unit tests, `tests/integration/` for anything that touches SQLite, the file system or MCP,
  `tests/e2e/` for M12. Shared fixtures live in `tests/fixtures/notes/<scenario>/`.
- **Markers**: `@pytest.mark.slow` for perf/e2e. The default `pytest` run excludes slow tests, and CI runs everything.
- **Time**: tests never read the real clock. They use `FixedClock` (M0).

## 2. Modules

| ID | Module | Package / files | Depends on | REQ IDs owned |
|---|---|---|---|---|
| [M0](modules/M0-foundation/spec.md) | Foundation | `pyproject.toml`, `cli.py` skeleton, `config.py`, `models.py`, `errors.py`, `clock.py`, `console.py`, `__main__.py` | — | CLI-01..07, CLI-09, CLI-10 |
| [M1](modules/M1-note-loader/spec.md) | Note loader | `parsing/note_loader.py` | M0 | NOTE-01..07, GEN-03 |
| [M2](modules/M2-people/spec.md) | People & owner resolution | `parsing/people.py` | M0 | PEOPLE-01..06 |
| [M3](modules/M3-dates/spec.md) | Due-date extraction & resolution | `parsing/dates.py` | M0 | DATE-01..06 |
| [M4](modules/M4-item-extraction/spec.md) | Action item extraction | `parsing/items.py` | M1, M2, M3 | ITEM-01..07 |
| [M5](modules/M5-dedup/spec.md) | Dedup & item IDs | `dedup.py` | M0 (consumes M4 output types) | DEDUP-01..06, ID-01, ID-02 |
| [M6](modules/M6-store/spec.md) | SQLite store | `store/db.py`, `store/repo.py` | M0 | STORE-01..06 |
| [M7](modules/M7-ingest/spec.md) | `ingest` command | `services/ingest.py`, `cli.py` | M1–M6 | INGEST-01..09, GEN-02 |
| [M8](modules/M8-list-done/spec.md) | `list` and `done` commands | `services/query.py`, `cli.py` | M3, M5, M6 | LIST-01..05, DONE-01..02 |
| [M9](modules/M9-email-render/spec.md) | Follow-up email rendering | `email/render.py`, `templates/followup.txt.j2` | M0 | FU-04 |
| [M10](modules/M10-gmail-mcp/spec.md) | Gmail MCP adapter | `email/gmail_mcp.py`, `email/outbox.py` | M0 | MCP-01..05, GEN-01 |
| [M11](modules/M11-followup/spec.md) | `followup` command | `services/followup.py`, `cli.py` | M2, M6, M8, M9, M10 | FU-01..03, FU-05, FU-06 |
| [M12](modules/M12-e2e-release/spec.md) | End-to-end, performance, release | `tests/e2e/`, `README.md`, CI | all | ACC-01..11, CLI-08 |

Every REQ ID in root spec §18 is owned by exactly one module. Shared contracts (the dataclasses in `models.py`) are
**defined in M0**. Later modules consume them and may add fields only by changing the M0 spec first.

## 3. Dependency graph and build order

```
                 ┌─> M1 Loader ─┐
                 ├─> M2 People ─┼─> M4 Items ─> M5 Dedup ─┐
M0 Foundation ───┼─> M3 Dates ──┘                         ├─> M7 Ingest ─> M8 List/Done ─┐
                 ├─> M6 Store ────────────────────────────┘                              ├─> M12 E2E
                 ├─> M9 Render ─┐                                                         │
                 └─> M10 MCP ───┴─────────────> M11 Followup ────────────────────────────┘
```

| Wave | Modules | Notes |
|---|---|---|
| 1 | M0 | Fixes the contracts (models, errors, config, Clock). Everything else waits on it |
| 2 | M1, M2, M3, M6, M9, M10 | These don't depend on each other and can be done in any order or in parallel |
| 3 | M4 | Needs M1–M3 |
| 4 | M5 | Pure. Can start in wave 2 using hand-built `ParsedItem` fixtures |
| 5 | M7 | First end-to-end path: notes → DB |
| 6 | M8, then M11 | M11 reuses the owner query from M8 |
| 7 | M12 | Needs the sample `notes/` folder (not yet in the repo) |

## 4. Status board

| Module | Spec | Tests written | Implemented | DoD | PR |
|---|---|---|---|---|---|
| M0 | Draft | ☑ | ☑ | ☑ | Pushed directly to main (7ba9395) |
| M1 | Draft | ☑ | ☑ | ☑ | [#1](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/1) |
| M2 | Draft | ☑ | ☑ | ☑ | [#2](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/2) |
| M3 | Draft | ☑ | ☑ | ☑ | [#3](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/3) |
| M4 | Draft | ☑ | ☑ | ☑ | [#4](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/4) |
| M5 | Draft | ☑ | ☑ | ☑ | [#5](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/5) |
| M6 | Draft | ☑ | ☑ | ☑ | [#6](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/6) |
| M7 | Draft | ☑ | ☑ | ☑ | [#7](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/7) |
| M8 | Draft | ☑ | ☑ | ☑ | [#8](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/8) |
| M9 | Draft | ☑ | ☑ | ☑ | [#9](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/9) |
| M10 | Draft | ☑ | ☑ | ☑ | [#10](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/10) |
| M11 | Draft | ☑ | ☑ | ☑ | [#11](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/11) |
| M12 | Draft | ☑ | ☑ | ☐ (T12.10 smoke test) | [#12](https://github.com/mohit-gupta-coditas/actiontrack-py/pull/12) |

## 5. Spec gaps found while decomposing

These came up while writing the module specs. Each has a **proposed resolution**, which the module specs already assume.
Once a gap is confirmed, the root spec is updated and the gap is marked resolved here (✅). G1 and G2 were confirmed with M6
(root spec §6, §8), G4 with M7 (root spec §9.1), G3 and G11 with M8 (root spec §9.2, §9.4),
G7, G12, G13, G14 and G15 with M9 (root spec §9.4, §11),
G8, G16–G22 with M10 (root spec §10.1),
Q5 and G23–G27 with M11 (root spec §9.4, §17, §19),
and G28–G37 with M12 (root spec §13.1, §13.4, §13.5, §17).

| # | Gap | Proposed resolution | Affects |
|---|---|---|---|
| G1 ✅ | An attendee listed only by first name, with no email, has no person key. `people.email` is `NOT NULL` in §8 | Person key = `name:<firstname>` for such attendees. `people.email` becomes nullable. `followup` for them fails with "cannot derive email" | M2, M6, M11 |
| G2 ✅ | Incremental ingest needs the parsed fields of every source to regroup items, and §8 `item_sources` stores only raw text | `item_sources` stores the parsed fields (owner_key, task, task_norm, due, checked, flags). PK becomes `(note_path, line_no)`, and `item_id` is reassigned on every regroup. Grouping always re-runs over **all** sources, so a change in config (threshold) applies everywhere | M5, M6, M7 |
| G3 ✅ | Are `orphaned` items shown in `list` and included in `followup`? | Hidden from the default `list` (shown with `--flag orphaned`) and excluded from `followup` | M8, M11 |
| G4 ✅ | A note file that was deleted from the folder | Its sources are removed and its items become `orphaned`. Only files under the scanned root are affected, so ingesting a different folder orphans nothing | M7 |
| G5 | A single-token owner that is not in the attendees (`Vikram to …`) | `owner_key = NULL`, flags `owner_not_attendee` + `unassigned`, `owner_raw` kept. A full name gets a derived key | M2, M4 |
| G6 | Meaning of `next Friday` (said on a Wednesday) | The occurrence in the **following calendar week** (Mon-start). `this Friday` / `Friday` = the next occurrence strictly after | M3 |
| G7 ✅ | In the subject `N open, M overdue`, does N include the overdue items? | N = open items that are **not** overdue. Total = N + M | M9 |
| G8 ✅ | The Gmail MCP server's `create_draft` argument names/shapes are unknown (Q6) | Configurable argument mapping (`arg_names`, `to_as_list`), validated against the tool's `inputSchema` | M10 |
| G9 | `ASAP` as a due phrase | Recognised. `due_date` NULL, flag `unparsed_due`, `due_raw = "ASAP"` | M3 |
| G10 | The same person appears with an explicit email in one note and a derived email in another | Known limitation: two keys. Future work: `people.yaml` aliases | M2 |
| G11 ✅ | An owner written as a full name who is not an attendee (G5) gets a derived key, but only attendees are stored in `people`, so `--owner` / `followup` could not find them | `PeopleRepo.find` also matches item owners missing from `people` (name = `owner_display`, email = the key if it is an email). Read-only: no schema or ingest change | M6, M8, M11 |
| G12 ✅ | The root spec names the template `followup.md.j2`, and the M9 spec names it plain-text `followup.txt.j2` | `templates/followup.txt.j2` (plain text). The root spec is renamed | M9 |
| G13 ✅ | An `overdue` item passed to the renderer with no due date, or one not before `today` | `render_followup` raises `ValueError` (a caller bug, like both sections being empty) | M9, M11 |
| G14 ✅ | A `sign_off` or task with trailing spaces breaks "no trailing whitespace" | Every rendered line is right-stripped, and the body ends with exactly one `\n` | M9 |
| G15 ✅ | The M9 template `(due {{ due or "no due date" }})` reads "(due no due date)" for an undated item | Undated open items read `(no due date)`; dated ones `(due 2026-11-28)` | M9 |
| G16 ✅ | The M10 spec used mcp v1 names (`FastMCP`, `streamablehttp_client`, camelCase result fields), but the installed SDK is mcp 2.x; `list_tools` is paginated | Target mcp 2.x (`mcp>=2.3,<3`): `MCPServer`, `streamable_http_client`, snake_case fields. Follow `next_cursor` until the draft tool is found | M10 |
| G17 ✅ | The outbox file name's `<owner-key-slug>` rule was undefined | Lowercase; runs of chars outside `[a-z0-9._-]` → `-`; trim `-`/`.`; empty → `unknown`. Timestamp = `now` in its own timezone | M10, M11 |
| G18 ✅ | The draft tool's schema may `require` arguments the client does not send | Fail before calling with `ExternalServiceError` naming them | M10 |
| G19 ✅ | A Gmail API draft ID is usually not the compose ID, so the built `#drafts?compose=<id>` link may not open the draft | Use a `link`/`url` returned by the server when present; otherwise the built link | M10 |
| G20 ✅ | The real server is the Gmail MCP connector (Q6), whose `create_draft` takes `to` as an array, but `to_as_list` defaulted to false | `McpConfig.to_as_list` defaults to `true`; other servers set it to false | M0, M10 |
| G21 ✅ | The connector returns the draft link as `viewUrl`, which the G19 parser ignored | Link keys are `viewUrl`, `link`, `url`, in that order | M10 |
| G22 ✅ | The connector is hosted and needs OAuth, and the adapter has no auth (REQ-MCP-05) | The adapter stays auth-free: `[gmail_mcp]` points at an already-authenticated endpoint (http `url` or stdio bridge). The endpoint is confirmed in M12's smoke test | M10, M12 |
| G23 ✅ | Which short ID the follow-up email shows for each item | The same prefix `list` prints: `shortest_unique_prefixes` over all item IDs (≥ 6 chars) | M11 |
| G24 ✅ | The MCP server creates a draft but returns neither an ID nor a link | Still a success: `drafts` row with `gmail_draft_id` NULL, stdout says the server returned no draft ID, exit 0 | M11 |
| G25 ✅ | `[gmail_mcp]` is misconfigured (no `url`/`command`, non-allowlisted `draft_tool`) | The adapter's config error surfaces as is (exit 2, or 1 for `ForbiddenToolError`). No outbox file: nothing was attempted | M11 |
| G26 ✅ | The draft is created but recording the `drafts` row fails (DB locked) | `FatalError` (exit 1) whose message names the draft's link or ID. No outbox, no second draft | M11 |
| G27 ✅ | An item with an unparsed due phrase (`ASAP`) has no `due_date`, so the email reads `(no due date)` | Kept for now (no M9 change). Showing the raw phrase is future work (root spec §19) | M9, M11 |
| G28 ✅ | The sample `notes/` folder is not in the repo, and `expected.yaml` can only be written by reading it | The user provides the real folder (no synthetic set). Until `notes/` and `tests/e2e/expected.yaml` exist, the e2e tests that need them **skip with a reason**, and M12's DoD stays unticked | M12 |
| G29 ✅ | The manual Gmail smoke test (T12.10) needs an authenticated MCP endpoint the CLI can reach, which CI and the agent lack | The README documents the exact steps. The PR lists T12.10 as pending, and `v0.1.0` is tagged only after the user confirms the draft appeared and nothing was sent | M12 |
| G30 ✅ | `trace_check.py` must detect REQ IDs owned by more than one module, but nothing says where ownership is read from; §18 also has a range row (`REQ-ACC-01..11`) | Ownership comes from the `REQ IDs owned` column of plan §2. Ranges (`CLI-01..07`, `REQ-ACC-01..11`) are expanded in both files | M12 |
| G31 ✅ | Root §13.1 names the entry point `actiontrack.cli:app`, but the code uses `actiontrack.cli:main` | `cli:main`: it adds UTF-8 stdio and the exit-code mapping. The root spec is fixed | M0, M12 |
| G32 ✅ | TC-M12-02 reads `list --json`, which shows only open items, but most sample duplicates end `[x]` in a later note | Read `list --json` and `list --status done --json` and check each duplicate across both | M12 |
| G33 ✅ | TC-M12-05 queries `--owner Rahul`, which is ambiguous (exit 2) because the sample has Rahul Mehta and Rahul Verma | The fixture note's only attendee is Rahul Mehta, and the test queries `--owner "Rahul Mehta"` | M12 |
| G34 ✅ | `expected.yaml` has no expected due per duplicate, and nothing checks `min_unique_items` | Each duplicate may carry a hand-computed `due` (D8) and `status`. TC-M12-01 checks the report's unique count ≥ `min_unique_items` | M12 |
| G35 ✅ | On Windows, `FORCE_COLOR` on a pipe makes rich use legacy Win32 console calls, so no ANSI reaches the pipe (TC-M12-06) | With `FORCE_COLOR` set, the consoles use `legacy_windows=False`: forced colour is ANSI on every OS | M0 |
| G36 ✅ | `actiontrack list \| head -3` prints `Error: internal error (OSError)` and exits 1 when the reader closes the pipe | A closed stdout ends the command quietly: stdout → `os.devnull`, exit 0, nothing on stderr. A bare `EPIPE` outside rich keeps Typer's quiet exit 1 | M0 |
| G37 ✅ | Every sample note's H1 is `# Meeting: <title>`, so emails read `From: Meeting: QA sync, …` | The H1 title drops a leading `Meeting:` / `Notes:` label (case-insensitive). Frontmatter titles are kept as written. Stored titles refresh when a note changes | M1 |

## 6. Traceability check (run before each PR)

```
# every REQ id in requirements.md §18 must appear in exactly one module spec and ≥1 tests.md
grep -o 'REQ-[A-Z]*-[0-9]*' spec/requirements.md | sort -u > /tmp/req
grep -rho 'REQ-[A-Z]*-[0-9]*' spec/modules/*/tests.md | sort -u > /tmp/tc
comm -23 /tmp/req /tmp/tc      # → requirements with no test case
```
(M12 adds this as `scripts/trace_check.py` and runs it in CI.)
