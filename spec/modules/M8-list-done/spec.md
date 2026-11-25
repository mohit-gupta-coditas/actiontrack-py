# M8 — `list` and `done` Commands

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M3 (`parse_user_date`), M5 (`resolve_prefix`, `shortest_unique_prefixes`), M6 (`PeopleRepo.find` gains item owners, G11) |
| **Files** | `actiontrack/services/query.py`, the `list` and `done` commands in `actiontrack/cli.py` |
| **REQ IDs** | REQ-LIST-01 … 05, REQ-DONE-01, REQ-DONE-02 |

## 1. Purpose
Let the user see tracked items with filters (as a table for people or as JSON), and mark items done by short ID.

## 2. Interface

```python
@dataclass(frozen=True)
class ItemView:
    id: str; short_id: str; owner_key: str | None; owner_display: str | None; owner_raw: str | None
    task: str; due_date: date | None; status: Literal["open", "done", "overdue"]
    flags: tuple[str, ...]; sources: tuple[SourceRef, ...]

def resolve_owner_query(q: str, people: PeopleRepo) -> Person       # UserInputError if 0 or >1 matches (with candidates)
def list_items(conn, *, owner: str | None, status: str | None, due_before: str | None,
               unassigned: bool, flag: str | None, clock: Clock, date_order: str) -> list[ItemView]
def mark_done(conn, prefix: str, *, clock: Clock) -> tuple[ItemView, bool]   # (item, changed)
```
`resolve_owner_query` is reused by M11. It matches through `PeopleRepo.find`, which covers attendees and, since M8, owners
that only appear on items: a full name that is not an attendee gets a derived key (G5) but no `people` row (G11).
`owner_raw` is carried so the table can show an ambiguous owner as typed.

## 3. `list` (REQ-LIST-01 … 05)

```
actiontrack list [--owner TEXT] [--status open|done|overdue] [--due-before DATE] [--unassigned] [--flag FLAG] [--json]
```

| Option | Behaviour |
|---|---|
| `--owner` | `resolve_owner_query`. 0 matches → `UserInputError('no person matches "x"')`. 2+ → `UserInputError('"Priya" matches 2 people', hint="Priya Shah <…>, Priya Nair <…> — use full name or email")`, exit 2 (REQ-LIST-05) |
| `--status` | Typer `Choice`. `open` includes overdue. When omitted → **open** (the default view, REQ-LIST-02) |
| `--due-before` | `parse_user_date(text, today=clock.today())`. Invalid → exit 2 |
| `--unassigned` | `owner_key IS NULL` |
| `--flag` | One of the `Flag` values (Choice). `orphaned` also enables `include_orphaned` |
| `--owner` + `--unassigned` | `UserInputError` (contradictory) |
| (no `--flag orphaned`) | Orphaned items are hidden (G3) |

`ItemView.status` = `overdue` if `is_overdue`, else the stored status.

**Table** (REQ-LIST-03), rich `Table` on stdout:

| ID | Owner | Task | Due | Status | Src |
|---|---|---|---|---|---|
| short id | display, `—` if none, `? Priya (ambiguous)` for ambiguous | task (wrapped) | ISO date or `—` | open / done / overdue | source count |

- Overdue rows are styled `red`, and the status cell reads `⚠ overdue` (the marker is always present, so colour is never the only signal).
- The footer on stderr reads `N items (M overdue)`, suppressed by `-q`.
- No results → `No items match.` on stderr (suppressed by `-q`), exit 0.
- Owner, task and other note text are printed literally, never as rich markup.

**JSON** (REQ-LIST-04), on stdout only:
```json
{"schema_version": 1, "generated_at": "2026-11-25T10:00:00+05:30", "today": "2026-11-25",
 "filters": {"owner": null, "status": "open", "due_before": null, "unassigned": false, "flag": null},  // as typed; status defaulted
 "items": [{"id": "<40hex>", "short_id": "a3f91c", "owner": {"key": "...", "name": "..."} | null,
            "task": "...", "due_date": "2026-11-20" | null, "status": "overdue",
            "flags": ["..."], "sources": [{"path": "...", "line": 12, "meeting_date": "...", "title": "..."}]}]}
```

## 4. `done` (REQ-DONE-01, REQ-DONE-02)

```
actiontrack done <id>
```
- `resolve_prefix(id, ItemRepo.ids())` (M5). Errors → exit 2 with candidates in the hint.
- `ItemRepo.mark_done(id, now=clock.now())`.
  - Changed → stdout `✓ a3f91c  send the revised quote  (Priya Shah)`, exit 0.
  - Already done → stderr `a3f91c is already done.`, exit 0.
  - The `(owner)` suffix is left out when the item has no owner.

## 5. Out of scope
Followup (M11). Editing items (future `assign` / `reopen`).

## 6. Open questions
None. G3 (orphaned hidden by default) and G11 (item owners are matchable) were confirmed with M8.
