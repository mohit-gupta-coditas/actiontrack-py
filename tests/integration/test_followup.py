from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from email import message_from_bytes, policy
from pathlib import Path
from typing import Any

import pytest

from actiontrack.clock import FixedClock
from actiontrack.config import Config, McpConfig
from actiontrack.dedup import DedupResult
from actiontrack.email.gmail_mcp import DraftResult, GmailMcpDraftSink
from actiontrack.errors import ExternalServiceError, FatalError, UserInputError
from actiontrack.models import Attendee, OwnerResolution
from actiontrack.services.followup import DraftNotCreatedError, FollowupResult, run_followup
from actiontrack.services.query import list_items
from actiontrack.store.repo import ItemRepo, PeopleRepo
from tests.integration.conftest import (
    FOLLOWUP,
    POOJA,
    PRIYA_NAIR,
    RAHUL,
    SEEDED,
    group,
    seed_followup,
    src,
    store_sources,
)
from tests.integration.mcp_fakes import RecordingSink

CLOCK = FixedClock(date(2026, 11, 25), datetime(2026, 11, 25, 9, 30).astimezone())


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    seed_followup(conn)
    return conn


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(db_path=tmp_path / "unused.db", outbox_dir=tmp_path / "outbox")


def followup(
    conn: sqlite3.Connection,
    owner: str,
    cfg: Config,
    sink: RecordingSink | None = None,
    *,
    dry_run: bool = False,
) -> FollowupResult:
    sink = sink or RecordingSink()
    return run_followup(
        owner, conn=conn, cfg=cfg, clock=CLOCK, dry_run=dry_run, sink_factory=sink.factory
    )


def drafts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM drafts ORDER BY id")]


def statuses(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM items")}


def test_TC_M11_01_one_draft_with_overdue_and_open_items(
    db: sqlite3.Connection, cfg: Config
) -> None:
    sink = RecordingSink()
    result = followup(db, "Rahul", cfg, sink)
    assert len(sink.drafts) == 1
    sent = sink.drafts[0]
    assert sent["to"] == RAHUL == result.recipient
    assert sent["subject"] == "Follow-up: your open action items (2 open, 1 overdue)"
    body = sent["body"]
    assert body.startswith("Hi Rahul,\n")
    assert body.index("Overdue (1):") < body.index("book the venue") < body.index("Open (2):")
    assert body.index("draft the agenda") < body.index("order the badges")
    assert "From: Meeting, 2026-11-18" in body
    assert result.email is not None and result.email.body == body
    assert result.draft == sink.result
    assert sink.configs == [cfg.gmail_mcp]


def test_TC_M11_02_draft_recorded(db: sqlite3.Connection, cfg: Config) -> None:
    result = followup(db, "Rahul", cfg)
    expected = {SEEDED["venue"], SEEDED["agenda"], FOLLOWUP["badges"]}
    assert set(result.item_ids) == expected
    [row] = drafts(db)
    assert row["owner_key"] == RAHUL
    assert row["recipient"] == RAHUL
    assert row["gmail_draft_id"] == "r-123"
    assert set(json.loads(row["item_ids"])) == expected
    assert row["created_at"] == CLOCK.now().isoformat()


def test_TC_M11_03_ambiguous_owner(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    with pytest.raises(UserInputError) as e:
        followup(db, "Priya", cfg, sink)
    assert e.value.hint is not None
    assert "priya.shah@coditas.com" in e.value.hint and PRIYA_NAIR in e.value.hint
    assert sink.configs == [] and drafts(db) == []


def test_TC_M11_04_unknown_owner(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    with pytest.raises(UserInputError, match="no person matches"):
        followup(db, "Nobody", cfg, sink)
    assert sink.configs == []


def test_TC_M11_05_no_open_items(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Dev", cfg, sink)
    assert result.person.full_name == "Dev Patel"
    assert result.email is None and result.recipient is None and result.draft is None
    assert result.item_ids == ()
    assert sink.configs == [] and drafts(db) == []


def test_TC_M11_06_orphaned_items_excluded(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Rahul", cfg, sink)
    assert SEEDED["orphan"] not in result.item_ids
    assert "renew the domain" not in sink.drafts[0]["body"]


def test_TC_M11_07_explicit_email_wins(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Pooja", cfg, sink)
    assert sink.drafts[0]["to"] == POOJA == result.recipient
    assert result.item_ids == (FOLLOWUP["logo"],)
    assert "approve the logo (no due date)" in sink.drafts[0]["body"]


def test_TC_M11_08_first_name_only_cannot_derive(conn: sqlite3.Connection, cfg: Config) -> None:
    who = OwnerResolution("name:priya", "Priya", "Priya", frozenset(), ())
    PeopleRepo(conn).upsert_many([Attendee("Priya", "Priya", None, None, "name:priya", None)])
    g = group(src(who, "call the vendor", "2026-11-18", due="2026-12-01"))
    store_sources(conn, *g.sources)
    ItemRepo(conn).apply_groups(DedupResult(groups=(g,), decisions=(), orphaned_ids=()))
    sink = RecordingSink()
    with pytest.raises(UserInputError) as e:
        followup(conn, "priya", cfg, sink)
    assert e.value.message == 'cannot derive email: no last name for "Priya"'
    assert e.value.hint == "use full names in the attendees list"
    assert sink.configs == [] and drafts(conn) == []


def test_TC_M11_09_dry_run_never_builds_the_sink(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Rahul", cfg, sink, dry_run=True)
    assert sink.configs == [] and sink.drafts == []
    assert result.draft is None
    assert result.recipient == RAHUL
    assert result.email is not None
    assert result.email.subject.endswith("(2 open, 1 overdue)")
    assert drafts(db) == []


def test_TC_M11_10_failed_draft_goes_to_the_outbox(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink(error=ExternalServiceError("timeout", hint="check gmail_mcp settings"))
    with pytest.raises(DraftNotCreatedError) as e:
        followup(db, "Rahul", cfg, sink)
    path = e.value.outbox_path
    assert path.parent == cfg.outbox_dir and path.name.startswith("rahul.mehta-coditas.com-")
    assert e.value.message == f"Draft could not be created: timeout. Email saved to {path}"
    assert e.value.hint == "check gmail_mcp settings"
    assert e.value.exit_code == 3
    msg = message_from_bytes(path.read_bytes(), policy=policy.default)
    assert msg["To"] == RAHUL
    assert msg["Subject"] == sink.drafts[0]["subject"]
    assert msg.get_content().replace("\r\n", "\n") == sink.drafts[0]["body"]
    assert drafts(db) == []


def test_TC_M11_11_items_unchanged(db: sqlite3.Connection, cfg: Config) -> None:
    before = statuses(db)
    followup(db, "Rahul", cfg)
    assert statuses(db) == before


def test_TC_M11_13_full_name_resolves_one_priya(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Priya Nair", cfg, sink)
    assert sink.drafts[0]["to"] == PRIYA_NAIR
    assert result.item_ids == (SEEDED["contract"],)


def test_TC_M11_14_ambiguous_items_excluded(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    result = followup(db, "Priya Shah", cfg, sink)
    assert result.item_ids == (SEEDED["quote"],)
    assert "update the budget" not in sink.drafts[0]["body"]


def test_TC_M11_15_short_ids_match_list(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink()
    followup(db, "Rahul", cfg, sink)
    views = list_items(db, owner="Rahul", clock=CLOCK)
    assert len(views) == 3
    for v in views:
        assert f"{v.task} (" in sink.drafts[0]["body"]
        assert f"[{v.short_id}]" in sink.drafts[0]["body"]


def test_TC_M11_16_draft_without_id_still_recorded(db: sqlite3.Connection, cfg: Config) -> None:
    sink = RecordingSink(result=DraftResult(None, None, {}))
    result = followup(db, "Rahul", cfg, sink)
    assert result.draft == DraftResult(None, None, {})
    [row] = drafts(db)
    assert row["gmail_draft_id"] is None


def test_TC_M11_17_config_error_writes_no_outbox(db: sqlite3.Connection, cfg: Config) -> None:
    bad = Config(db_path=cfg.db_path, outbox_dir=cfg.outbox_dir, gmail_mcp=McpConfig("http"))
    with pytest.raises(UserInputError, match=r"gmail_mcp\.url is not set"):
        run_followup(
            "Rahul",
            conn=db,
            cfg=bad,
            clock=CLOCK,
            dry_run=False,
            sink_factory=GmailMcpDraftSink,
        )
    assert not cfg.outbox_dir.exists()
    assert drafts(db) == []


def test_TC_M11_18_record_failure_names_the_draft(db: sqlite3.Connection, cfg: Config) -> None:
    db.execute("DROP TABLE drafts")
    sink = RecordingSink()
    with pytest.raises(FatalError) as e:
        followup(db, "Rahul", cfg, sink)
    assert e.value.message.startswith("draft created (https://mail.example/r-123) but not recorded")
    assert len(sink.drafts) == 1
    assert not cfg.outbox_dir.exists()


def test_record_failure_without_draft_id(db: sqlite3.Connection, cfg: Config) -> None:
    db.execute("DROP TABLE drafts")
    with pytest.raises(FatalError, match=r"draft created \(no draft ID returned\)"):
        followup(db, "Rahul", cfg, RecordingSink(result=DraftResult(None, None, {})))
