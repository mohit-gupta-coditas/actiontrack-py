from __future__ import annotations

import inspect
import time
from collections.abc import Iterator
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from types import MappingProxyType
from typing import Any

import anyio
import pytest

from actiontrack.config import McpConfig
from actiontrack.console import make_output
from actiontrack.email.gmail_mcp import (
    ALLOWED_TOOLS,
    DraftResult,
    GmailMcpDraftSink,
    _parse_result,
)
from actiontrack.email.outbox import STATUS_HEADER, write_outbox
from actiontrack.errors import ExternalServiceError, ForbiddenToolError, UserInputError
from tests.integration.mcp_fakes import FAKES, FORBIDDEN, FakeGmail, schema, text_result

TO = "priya.shah@coditas.com"
SUBJECT = "Follow-up: your open action items (2 open)"
BODY = "Hi Priya,\n\nSecret body text\n"


@pytest.fixture(autouse=True)
def _never_sends() -> Iterator[None]:
    """TC-M10-02: whatever a test does, no fake ever receives a send tool call."""
    FAKES.clear()
    yield
    called = {name for fake in FAKES for name, _ in fake.calls}
    assert not called & set(FORBIDDEN), called
    FAKES.clear()


def sink(fake: FakeGmail, **cfg: Any) -> GmailMcpDraftSink:
    return GmailMcpDraftSink(McpConfig(**cfg), session_factory=fake.session_factory())


def draft(adapter: GmailMcpDraftSink) -> DraftResult:
    return adapter.create_draft(to=TO, subject=SUBJECT, body=BODY)


def test_TC_M10_01_create_draft_calls_the_tool_once_with_mapped_args() -> None:
    fake = FakeGmail()
    result = draft(sink(fake))
    assert fake.calls == [("create_draft", {"to": TO, "subject": SUBJECT, "body": BODY})]
    assert result.draft_id == "r-123"
    assert result.link == "https://mail.google.com/mail/#drafts?compose=r-123"
    assert result.raw["structured_content"] == {"id": "r-123"}


def test_TC_M10_02_repeated_use_and_failures_never_send() -> None:
    fake = FakeGmail()
    adapter = sink(fake)
    draft(adapter)
    draft(adapter)
    with pytest.raises(ForbiddenToolError):
        anyio.run(adapter._call, "send_message", {"to": TO})
    assert [name for name, _ in fake.calls] == ["create_draft", "create_draft"]


@pytest.mark.parametrize("tool", [*FORBIDDEN, "create_draft_and_send"])
def test_TC_M10_03_call_rejects_any_tool_outside_the_allowlist(tool: str) -> None:
    fake = FakeGmail()
    with pytest.raises(ForbiddenToolError, match=tool):
        anyio.run(sink(fake)._call, tool, {"to": TO})
    assert fake.calls == []


def test_TC_M10_04_config_cannot_point_the_adapter_at_a_send_tool() -> None:
    assert frozenset({"create_draft"}) == ALLOWED_TOOLS
    with pytest.raises(ForbiddenToolError, match="send_message"):
        GmailMcpDraftSink(McpConfig(draft_tool="send_message", command="npx"))


def test_TC_M10_05_create_draft_is_the_only_public_method() -> None:
    public = {
        name
        for name, value in inspect.getmembers(GmailMcpDraftSink)
        if not name.startswith("_") and callable(value)
    }
    assert public == {"create_draft"}
    adapter = sink(FakeGmail())
    assert [n for n in vars(adapter) if not n.startswith("_")] == []


def test_TC_M10_06_server_without_create_draft() -> None:
    fake = FakeGmail(draft_schema=None)
    with pytest.raises(ExternalServiceError, match='does not expose "create_draft"') as e:
        draft(sink(fake))
    assert e.value.hint == "check gmail_mcp settings"
    assert fake.calls == []


def test_TC_M10_07_argument_names_mismatch_lists_expected_and_actual() -> None:
    fake = FakeGmail(draft_schema=schema("recipients", "subject", "body"))
    with pytest.raises(ExternalServiceError) as e:
        draft(sink(fake))
    assert "expected to, subject, body" in e.value.message
    assert "the server has body, recipients, subject" in e.value.message
    assert fake.calls == []


def test_TC_M10_08_mapped_argument_names_and_list_recipient() -> None:
    fake = FakeGmail(draft_schema=schema("recipients", "subject", "body"))
    names = MappingProxyType({"to": "recipients", "subject": "subject", "body": "body"})
    draft(sink(fake, arg_names=names, to_as_list=True))
    assert fake.calls == [("create_draft", {"recipients": [TO], "subject": SUBJECT, "body": BODY})]


def test_TC_M10_09_tool_error_result_carries_the_server_text() -> None:
    fake = FakeGmail(result=text_result("quota exceeded", is_error=True))
    with pytest.raises(ExternalServiceError, match="quota exceeded"):
        draft(sink(fake))


def test_TC_M10_10_slow_server_times_out() -> None:
    fake = FakeGmail(delay=2.0)
    start = time.monotonic()
    with pytest.raises(ExternalServiceError, match=r"timed out after 0\.5 s"):
        draft(sink(fake, timeout_s=0.5))
    assert time.monotonic() - start < 1.5


def test_TC_M10_11_stdio_launch_failure_is_external() -> None:
    adapter = GmailMcpDraftSink(McpConfig(command="does-not-exist-xyz", timeout_s=10))
    with pytest.raises(ExternalServiceError) as e:
        draft(adapter)
    assert e.value.exit_code == 3


def test_TC_M10_12_stdio_without_command_names_the_setting() -> None:
    with pytest.raises(UserInputError, match=r"gmail_mcp\.command"):
        GmailMcpDraftSink(McpConfig(transport="stdio"))
    with pytest.raises(UserInputError, match=r"gmail_mcp\.url"):
        GmailMcpDraftSink(McpConfig(transport="http"))
    GmailMcpDraftSink(McpConfig(transport="http", url="http://localhost:1/mcp"))  # no I/O yet


@pytest.mark.parametrize(
    ("result", "draft_id", "link"),
    [
        (text_result("ok", structured={"id": "r-1"}), "r-1", "#drafts?compose=r-1"),
        (text_result('{"draftId": "r-2"}'), "r-2", "#drafts?compose=r-2"),
        (text_result('{"draft": {"id": 42}}'), "42", "#drafts?compose=42"),
        (text_result("Draft created."), None, None),
        (
            text_result("ok", structured={"id": "r-3", "link": "https://mail.example/d/3"}),
            "r-3",
            "https://mail.example/d/3",
        ),
        (text_result('{"draftId": "r-4", "url": "https://mail.example/d/4"}'), "r-4",
         "https://mail.example/d/4"),
        (text_result('{"id": "r-5"}', structured={"status": "ok"}), "r-5", "#drafts?compose=r-5"),
    ],
)  # fmt: skip
def test_TC_M10_13_result_forms(result: Any, draft_id: str | None, link: str | None) -> None:
    parsed = _parse_result(result)
    assert parsed.draft_id == draft_id
    if link is None:
        assert parsed.link is None
    else:
        assert parsed.link is not None and parsed.link.endswith(link)


def test_TC_M10_14_debug_logs_show_tool_and_keys_but_no_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    make_output(no_color=True, quiet=False, verbosity=2, env={})
    draft(sink(FakeGmail()))
    err = capsys.readouterr().err
    assert "create_draft" in err
    assert "['body', 'subject', 'to']" in err
    for value in (TO, SUBJECT, "Secret body text"):
        assert value not in err


def _read(path: Path) -> EmailMessage:
    msg = message_from_bytes(path.read_bytes(), policy=policy.default)
    assert isinstance(msg, EmailMessage)
    return msg


def test_TC_M10_15_outbox_never_overwrites_and_round_trips(tmp_path: Path) -> None:
    now = datetime(2026, 11, 26, 9, 30, 5).astimezone()
    kwargs: dict[str, Any] = {"owner_key": TO, "to": TO, "subject": SUBJECT, "now": now}
    first = write_outbox(outbox_dir=tmp_path, body=BODY, **kwargs)
    second = write_outbox(outbox_dir=tmp_path, body="Second body ✓\n", **kwargs)
    assert first.name == "priya.shah-coditas.com-20261126T093005.eml"
    assert second.name == "priya.shah-coditas.com-20261126T093005-2.eml"
    for path, body in ((first, BODY), (second, "Second body ✓\n")):
        msg = _read(path)
        assert msg["To"] == TO
        assert msg["Subject"] == SUBJECT
        assert msg[STATUS_HEADER] == "draft-not-created"
        assert msg["Date"].datetime == now
        assert msg.get_content().replace("\r\n", "\n") == body  # .eml lines end in CRLF


@pytest.mark.parametrize(
    ("owner_key", "slug"),
    [(TO, "priya.shah-coditas.com"), ("name:Priya", "name-priya"), ("@@@", "unknown")],
)
def test_TC_M10_16_outbox_file_names_use_a_safe_slug(
    tmp_path: Path, owner_key: str, slug: str
) -> None:
    outbox = tmp_path / "new" / "outbox"
    now = datetime(2026, 11, 26, 9, 30, 5).astimezone()
    path = write_outbox(
        outbox_dir=outbox, owner_key=owner_key, to=TO, subject=SUBJECT, body=BODY, now=now
    )
    assert path == outbox / f"{slug}-20261126T093005.eml"


def test_TC_M10_17_tool_requiring_an_unsent_argument() -> None:
    fake = FakeGmail(draft_schema=schema("to", "subject", "body", "cc"))
    with pytest.raises(ExternalServiceError, match="also requires cc"):
        draft(sink(fake))
    assert fake.calls == []


def test_TC_M10_17_optional_extra_arguments_are_fine() -> None:
    fake = FakeGmail(draft_schema=schema("to", "subject", "body", "cc", required=("to",)))
    draft(sink(fake))
    assert len(fake.calls) == 1


def test_TC_M10_18_draft_tool_on_a_later_tool_page() -> None:
    fake = FakeGmail(page_size=2)  # create_draft is the fourth tool: page 2
    assert draft(sink(fake)).draft_id == "r-123"
    assert [name for name, _ in fake.calls] == ["create_draft"]
