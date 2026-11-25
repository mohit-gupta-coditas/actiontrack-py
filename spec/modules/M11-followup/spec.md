# M11 — `followup` Command

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M2 (`derive_email`), M6, M8 (`resolve_owner_query`), M9, M10 |
| **Files** | `actiontrack/services/followup.py`, the `followup` command in `actiontrack/cli.py` |
| **REQ IDs** | REQ-FU-01, 02, 03, 05, 06 |

## 1. Purpose
For one owner, gather their open and overdue items, render the follow-up email, and create a Gmail **draft** for them to review.
Never send.

## 2. Interface

```python
@dataclass(frozen=True)
class FollowupResult:
    person: Person; recipient: str; email: RenderedEmail; item_ids: tuple[str, ...]
    draft: DraftResult | None          # None for --dry-run
    outbox_path: Path | None           # set when the draft failed and the email was saved locally

def run_followup(owner_query: str, *, conn, cfg: Config, clock: Clock, dry_run: bool,
                 sink_factory: Callable[[McpConfig], DraftSink]) -> FollowupResult
```

CLI: `actiontrack followup <owner> [--dry-run]`

## 3. Steps

| # | Step | Failure → |
|---|---|---|
| 1 | `resolve_owner_query(owner, PeopleRepo)` (M8) (REQ-FU-01) | 0 or 2+ matches → `UserInputError` with candidates, exit 2, no draft |
| 2 | `ItemRepo.query(ItemFilter(owner_keys=(person.key,), status="open"))`. Orphaned and ambiguous items are excluded (G3, Q5 ✅) (REQ-FU-02) | None → stderr `No open items for <name>. No draft created.`, exit 0 |
| 3 | Recipient (REQ-FU-03): `person.email` if set, else `derive_email(person.full_name, domain=cfg.email_domain)` | No last name → `UserInputError('cannot derive email: no last name for "Priya"', hint="use full names in the attendees list")`, exit 2 |
| 4 | Split items into overdue/open, map them to `EmailItem` (most recent source for the meeting title/date; `short_id` = the `list` prefix from `shortest_unique_prefixes(ItemRepo.ids())`, G23), `render_followup` (M9). Undated items, `ASAP` included, read `(no due date)` (G27) | — |
| 5 | `--dry-run` (REQ-FU-05): print `To:`, `Subject:`, a blank line, then the body to **stdout**. `sink_factory` is **not called**. Exit 0 | — |
| 6 | `sink_factory(cfg.gmail_mcp).create_draft(to, subject, body)` (REQ-FU-06) | `ExternalServiceError` from `create_draft` → `write_outbox(...)`, stderr `Draft could not be created: <msg>. Email saved to <path>`, exit 3. Errors from `sink_factory` itself (config: no `url`/`command`, `ForbiddenToolError`) propagate unchanged, no outbox (G25) |
| 7 | `DraftRepo.record(...)`. stdout `Draft created for Priya Shah <priya.shah@coditas.com>: <link or id>`, or `… (the server returned no draft ID)` when it returned neither (G24, row recorded with `gmail_draft_id` NULL). stderr reminder `Review and send it from Gmail. actiontrack never sends email.` Exit 0 | `sqlite3.Error` → `FatalError('draft created (<link or id>) but not recorded: <msg>')`, exit 1 (G26) |

## 4. Invariants
- No code path calls anything other than `DraftSink.create_draft` (REQ-GEN-01 is enforced in M10 and re-checked here end-to-end).
- One invocation creates **at most one** draft.
- Items are **not** changed by followup (no status change).

## 5. Out of scope
Batch follow-ups for everyone (future). Editing or deleting drafts.

## 6. Open questions
None. Q5 (ambiguous excluded) and G23–G27 were confirmed with M11; G3 (orphaned excluded) with M8.
