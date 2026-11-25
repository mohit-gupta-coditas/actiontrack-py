# actiontrack — Implementation Plan (Spec-Driven Development)

| | |
|---|---|
| **Root spec** | [requirements.md](requirements.md). This is the source of truth, and module specs are derived from it |
| **Status** | In progress. M0, M1, M2, M3, M4 and M5 done |
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
| M6 | Draft | ☐ | ☐ | ☐ | — |
| M7 | Draft | ☐ | ☐ | ☐ | — |
| M8 | Draft | ☐ | ☐ | ☐ | — |
| M9 | Draft | ☐ | ☐ | ☐ | — |
| M10 | Draft | ☐ | ☐ | ☐ | — |
| M11 | Draft | ☐ | ☐ | ☐ | — |
| M12 | Draft | ☐ | ☐ | ☐ | — |

## 5. Spec gaps found while decomposing

These came up while writing the module specs. Each has a **proposed resolution**, which the module specs already assume.
Once a gap is confirmed, the root spec is updated and the gap is marked resolved here.

| # | Gap | Proposed resolution | Affects |
|---|---|---|---|
| G1 | An attendee listed only by first name, with no email, has no person key. `people.email` is `NOT NULL` in §8 | Person key = `name:<firstname>` for such attendees. `people.email` becomes nullable. `followup` for them fails with "cannot derive email" | M2, M6, M11 |
| G2 | Incremental ingest needs the parsed fields of every source to regroup items, and §8 `item_sources` stores only raw text | `item_sources` stores the parsed fields (owner_key, task, task_norm, due, checked, flags). PK becomes `(note_path, line_no)`, and `item_id` is reassigned on every regroup. Grouping always re-runs over **all** sources, so a change in config (threshold) applies everywhere | M5, M6, M7 |
| G3 | Are `orphaned` items shown in `list` and included in `followup`? | Hidden from the default `list` (shown with `--flag orphaned`) and excluded from `followup` | M8, M11 |
| G4 | A note file that was deleted from the folder | Its sources are removed and its items become `orphaned`. Only files under the scanned root are affected, so ingesting a different folder orphans nothing | M7 |
| G5 | A single-token owner that is not in the attendees (`Vikram to …`) | `owner_key = NULL`, flags `owner_not_attendee` + `unassigned`, `owner_raw` kept. A full name gets a derived key | M2, M4 |
| G6 | Meaning of `next Friday` (said on a Wednesday) | The occurrence in the **following calendar week** (Mon-start). `this Friday` / `Friday` = the next occurrence strictly after | M3 |
| G7 | In the subject `N open, M overdue`, does N include the overdue items? | N = open items that are **not** overdue. Total = N + M | M9 |
| G8 | The Gmail MCP server's `create_draft` argument names/shapes are unknown (Q6) | Configurable argument mapping (`arg_names`, `to_as_list`), validated against the tool's `inputSchema` | M10 |
| G9 | `ASAP` as a due phrase | Recognised. `due_date` NULL, flag `unparsed_due`, `due_raw = "ASAP"` | M3 |
| G10 | The same person appears with an explicit email in one note and a derived email in another | Known limitation: two keys. Future work: `people.yaml` aliases | M2 |

## 6. Traceability check (run before each PR)

```
# every REQ id in requirements.md §18 must appear in exactly one module spec and ≥1 tests.md
grep -o 'REQ-[A-Z]*-[0-9]*' spec/requirements.md | sort -u > /tmp/req
grep -rho 'REQ-[A-Z]*-[0-9]*' spec/modules/*/tests.md | sort -u > /tmp/tc
comm -23 /tmp/req /tmp/tc      # → requirements with no test case
```
(M12 adds this as `scripts/trace_check.py` and runs it in CI.)
