"""The `followup` use case: one owner's open items → a rendered email → one Gmail draft (M11).

Never sends: the only outward call is `DraftSink.create_draft` (REQ-GEN-01). Items are read,
never changed.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from actiontrack.clock import Clock
from actiontrack.config import Config, McpConfig
from actiontrack.dedup import shortest_unique_prefixes
from actiontrack.email.gmail_mcp import DraftResult, DraftSink
from actiontrack.email.outbox import write_outbox
from actiontrack.email.render import EmailItem, RenderedEmail, render_followup
from actiontrack.errors import ExternalServiceError, FatalError, UserInputError
from actiontrack.models import Person
from actiontrack.parsing.people import derive_email
from actiontrack.services.query import resolve_owner_query
from actiontrack.store.repo import DraftRepo, ItemFilter, ItemRepo, ItemRow, PeopleRepo


@dataclass(frozen=True)
class FollowupResult:
    person: Person
    recipient: str | None  # None, like `email`, when the person has no open items
    email: RenderedEmail | None
    item_ids: tuple[str, ...]
    draft: DraftResult | None  # None for --dry-run or no open items


class DraftNotCreatedError(ExternalServiceError):
    """The MCP call failed; the email was saved to the outbox instead (REQ-MCP-04)."""

    def __init__(self, message: str, *, outbox_path: Path, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)
        self.outbox_path = outbox_path


def run_followup(
    owner_query: str,
    *,
    conn: sqlite3.Connection,
    cfg: Config,
    clock: Clock,
    dry_run: bool,
    sink_factory: Callable[[McpConfig], DraftSink],
) -> FollowupResult:
    person = resolve_owner_query(owner_query, PeopleRepo(conn))
    items = ItemRepo(conn)
    today = clock.today()
    # Orphaned items are excluded by the filter (G3); ambiguous ones have no owner_key (Q5).
    rows = items.query(ItemFilter(owner_keys=(person.key,), status="open"), today=today)
    if not rows:
        return FollowupResult(person, None, None, (), None)
    recipient = _recipient(person, domain=cfg.email_domain)

    short_ids = shortest_unique_prefixes(items.ids())  # the prefixes `list` prints (G23)
    email = render_followup(
        first_name=person.first_name,
        overdue=[_email_item(r, short_ids[r.id]) for r in rows if r.is_overdue],
        open_=[_email_item(r, short_ids[r.id]) for r in rows if not r.is_overdue],
        today=today,
        sign_off=cfg.sign_off,
    )
    item_ids = tuple(r.id for r in rows)
    if dry_run:
        return FollowupResult(person, recipient, email, item_ids, None)

    sink = sink_factory(cfg.gmail_mcp)  # config errors surface here, before any call (G25)
    try:
        draft = sink.create_draft(to=recipient, subject=email.subject, body=email.body)
    except ExternalServiceError as e:
        path = write_outbox(
            outbox_dir=cfg.outbox_dir,
            owner_key=person.key,
            to=recipient,
            subject=email.subject,
            body=email.body,
            now=clock.now(),
        )
        raise DraftNotCreatedError(
            f"Draft could not be created: {e.message}. Email saved to {path}",
            outbox_path=path,
            hint=e.hint,
        ) from e

    try:
        DraftRepo(conn).record(
            owner_key=person.key,
            recipient=recipient,
            gmail_draft_id=draft.draft_id,
            item_ids=item_ids,
            now=clock.now(),
        )
    except sqlite3.Error as e:
        ref = draft.link or draft.draft_id or "no draft ID returned"
        raise FatalError(f"draft created ({ref}) but not recorded: {e}") from e  # G26
    return FollowupResult(person, recipient, email, item_ids, draft)


def _recipient(person: Person, *, domain: str) -> str:
    if person.email:
        return person.email
    try:
        return derive_email(person.full_name, domain=domain)
    except UserInputError as e:
        raise UserInputError(e.message, hint="use full names in the attendees list") from e


def _email_item(r: ItemRow, short_id: str) -> EmailItem:
    latest = r.sources[-1]  # sources are ordered by meeting date
    return EmailItem(
        short_id=short_id,
        task=r.task,
        due_date=r.due_date,
        meeting_title=latest.note_title,
        meeting_date=latest.meeting_date,
    )
