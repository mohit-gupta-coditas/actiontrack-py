from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from actiontrack.cli import run
from actiontrack.config import McpConfig
from actiontrack.email import gmail_mcp
from actiontrack.errors import ExternalServiceError
from actiontrack.store.db import connect
from tests.integration.conftest import PRIYA_NAIR, RAHUL, seed_followup
from tests.integration.mcp_fakes import FAKES, FORBIDDEN, FakeGmail, RecordingSink

TODAY = date(2026, 11, 25)
REMINDER = "Review and send it from Gmail. actiontrack never sends email."


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The followup DB (seeded M8 items plus the M11 extras), used through ACTIONTRACK_DB."""
    path = tmp_path / "db.sqlite"
    monkeypatch.setenv("ACTIONTRACK_DB", str(path))
    monkeypatch.setenv("ACTIONTRACK_TODAY", TODAY.isoformat())
    conn = connect(path)
    try:
        seed_followup(conn)
    finally:
        conn.close()
    return path


@pytest.fixture
def outbox(isolated_env: Path) -> Path:
    """The default outbox folder under the test's platformdirs home."""
    return isolated_env / "data" / "actiontrack" / "outbox"


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> RecordingSink:
    """Replaces `GmailMcpDraftSink`, which the command imports when it runs."""
    fake = RecordingSink()
    monkeypatch.setattr(gmail_mcp, "GmailMcpDraftSink", fake.factory)
    return fake


@pytest.fixture(autouse=True)
def _never_sends() -> Iterator[None]:
    FAKES.clear()
    yield
    called = {name for fake in FAKES for name, _ in fake.calls}
    assert not called & set(FORBIDDEN), called
    FAKES.clear()


def drafts(db: Path) -> list[sqlite3.Row]:
    conn = connect(db)
    try:
        return conn.execute("SELECT * FROM drafts").fetchall()
    finally:
        conn.close()


def test_TC_M11_01_draft_created(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "Rahul"]) == 0
    [sent] = sink.drafts
    assert sent["to"] == RAHUL
    assert sent["subject"].endswith("(2 open, 1 overdue)")


def test_TC_M11_02_messages_and_record(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "Rahul"]) == 0
    out, err = capsys.readouterr()
    assert out == f"Draft created for Rahul Mehta <{RAHUL}>: https://mail.example/r-123\n"
    assert REMINDER in err and "never sends" in err
    assert len(drafts(db)) == 1


def test_TC_M11_03_ambiguous_owner(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "Priya"]) == 2
    err = capsys.readouterr().err
    assert '"Priya" matches 2 people' in err
    assert "Priya Shah <priya.shah@coditas.com>" in err and PRIYA_NAIR in err
    assert sink.configs == []


def test_TC_M11_04_unknown_owner(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "Nobody"]) == 2
    assert 'no person matches "Nobody"' in capsys.readouterr().err
    assert sink.configs == []


def test_TC_M11_05_no_open_items(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "dev"]) == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert "No open items for Dev Patel. No draft created." in err
    assert sink.configs == []


def test_TC_M11_09_dry_run(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["followup", "Rahul", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    lines = out.splitlines()
    assert lines[0] == f"To: {RAHUL}"
    assert lines[1] == "Subject: Follow-up: your open action items (2 open, 1 overdue)"
    assert lines[2] == ""
    assert lines[3] == "Hi Rahul,"
    assert out.endswith("Thanks\n")
    assert "Dry run: no draft created." in err
    assert sink.configs == []
    assert drafts(db) == []


def test_TC_M11_10_failure_exit_3_with_outbox(
    db: Path, sink: RecordingSink, outbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sink.error = ExternalServiceError("timeout")
    assert run(["followup", "Rahul"]) == 3
    [path] = outbox.iterdir()
    err = capsys.readouterr().err
    assert f"Error: Draft could not be created: timeout. Email saved to {path}" in err
    assert drafts(db) == []


def test_TC_M11_12_end_to_end_with_fake_mcp_server(
    db: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGmail()

    def transport(cfg: McpConfig) -> gmail_mcp.SessionFactory:
        return fake.session_factory()

    monkeypatch.setattr(gmail_mcp, "_transport_factory", transport)
    assert run(["followup", "Rahul"]) == 0
    assert [name for name, _ in fake.calls] == ["create_draft"]
    assert fake.calls[0][1]["to"] == [RAHUL]
    out = capsys.readouterr().out
    assert out.startswith(f"Draft created for Rahul Mehta <{RAHUL}>: https://mail.google.com/")
    [row] = drafts(db)
    assert row["gmail_draft_id"] == "r-123"


def test_TC_M11_16_no_draft_id_message(
    db: Path, sink: RecordingSink, capsys: pytest.CaptureFixture[str]
) -> None:
    sink.result = gmail_mcp.DraftResult(None, None, {})
    assert run(["followup", "Rahul"]) == 0
    out = capsys.readouterr().out
    assert out == f"Draft created for Rahul Mehta <{RAHUL}> (the server returned no draft ID)\n"


def test_TC_M11_17_missing_url_exit_2_no_outbox(
    db: Path, tmp_path: Path, outbox: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[gmail_mcp]\ntransport = "http"\n', encoding="utf-8")
    assert run(["--config", str(config), "followup", "Rahul"]) == 2
    assert "gmail_mcp.url is not set" in capsys.readouterr().err
    assert not outbox.exists()
    assert drafts(db) == []


def test_followup_help_has_examples(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["followup", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out and "actiontrack followup priya" in out
