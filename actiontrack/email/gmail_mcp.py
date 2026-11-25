"""Gmail draft adapter: an MCP client that can only create drafts (M10, REQ-MCP-01..05, REQ-GEN-01).

Sending is impossible by construction: the one public method is `create_draft`, and `_call`
checks the hard-coded `ALLOWED_TOOLS` before any tool call. Credentials are the MCP server's
job; this module never reads, stores or logs them, and logs argument keys, never values.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol
from urllib.parse import quote

import anyio

from actiontrack.config import McpConfig
from actiontrack.errors import (
    ActionTrackError,
    ExternalServiceError,
    ForbiddenToolError,
    UserInputError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mcp import ClientSession
    from mcp.types import CallToolResult, Tool

ALLOWED_TOOLS: Final = frozenset({"create_draft"})

_ARG_KEYS: Final = ("to", "subject", "body")
_LINK: Final = "https://mail.google.com/mail/#drafts?compose={}"
_HINT: Final = "check gmail_mcp settings"

log = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager["ClientSession"]]
"""Opens a connected, not yet initialized `mcp.ClientSession`."""


@dataclass(frozen=True)
class DraftResult:
    draft_id: str | None
    link: str | None
    raw: Mapping[str, Any]


class DraftSink(Protocol):
    def create_draft(self, *, to: str, subject: str, body: str) -> DraftResult: ...


class GmailMcpDraftSink:
    """Implements `DraftSink` over the Gmail MCP server named in `[gmail_mcp]`."""

    def __init__(self, cfg: McpConfig, *, session_factory: SessionFactory | None = None) -> None:
        if cfg.draft_tool not in ALLOWED_TOOLS:
            raise ForbiddenToolError(
                f'gmail_mcp.draft_tool "{cfg.draft_tool}" is not allowed',
                hint=f"only {', '.join(sorted(ALLOWED_TOOLS))} can be used",
            )
        self._cfg = cfg
        self._open_session = session_factory or _transport_factory(cfg)
        self._session: ClientSession | None = None

    def create_draft(self, *, to: str, subject: str, body: str) -> DraftResult:
        try:
            return anyio.run(self._create_draft, to, subject, body)
        except BaseException as e:
            raise _external_error(e, self._cfg.timeout_s) from e

    async def _create_draft(self, to: str, subject: str, body: str) -> DraftResult:
        cfg = self._cfg
        with anyio.fail_after(cfg.timeout_s):
            async with self._open_session() as session:
                self._session = session
                try:
                    await session.initialize()
                    tool = await _find_tool(session, cfg.draft_tool)
                    names = {key: cfg.arg_names[key] for key in _ARG_KEYS}
                    _check_schema(tool, list(names.values()))
                    args: dict[str, Any] = {
                        names["to"]: [to] if cfg.to_as_list else to,
                        names["subject"]: subject,
                        names["body"]: body,
                    }
                    result = await self._call(cfg.draft_tool, args)
                finally:
                    self._session = None
        if result.is_error:
            raise ExternalServiceError(
                f'MCP tool "{cfg.draft_tool}" failed: {_text(result) or "no details"}', hint=_HINT
            )
        return _parse_result(result)

    async def _call(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """The only path to `call_tool`. The allowlist is checked first (REQ-MCP-03)."""
        if name not in ALLOWED_TOOLS:
            raise ForbiddenToolError(f'refusing to call MCP tool "{name}": not in the allowlist')
        if self._session is None:
            raise RuntimeError("no open MCP session")
        log.debug("calling MCP tool %s with argument keys %s", name, sorted(arguments))
        return await self._session.call_tool(name, arguments)


def _transport_factory(cfg: McpConfig) -> SessionFactory:
    """A session factory for `cfg.transport`. Missing settings fail here, at construction."""
    if cfg.transport == "stdio":
        if not cfg.command:
            raise UserInputError(
                "gmail_mcp.command is not set",
                hint="set the MCP server launch command in the config",
            )
        command, cmd_args = cfg.command, list(cfg.args)

        @asynccontextmanager
        async def open_stdio() -> AsyncIterator[ClientSession]:
            from mcp import ClientSession, StdioServerParameters, stdio_client

            params = StdioServerParameters(command=command, args=cmd_args)
            async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
                yield s

        return open_stdio

    if not cfg.url:
        raise UserInputError(
            "gmail_mcp.url is not set", hint="set the MCP server URL in the config"
        )
    url = cfg.url

    @asynccontextmanager
    async def open_http() -> AsyncIterator[ClientSession]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as (read, write), ClientSession(read, write) as s:
            yield s

    return open_http


async def _find_tool(session: ClientSession, name: str) -> Tool:
    """The tool called `name`, following `list_tools` pages (REQ-MCP-02, G16)."""
    from mcp.types import PaginatedRequestParams

    cursor: str | None = None
    seen: set[str] = set()
    while True:
        params = PaginatedRequestParams(cursor=cursor) if cursor else None
        page = await session.list_tools(params=params)
        for tool in page.tools:
            if tool.name == name:
                return tool
        cursor = page.next_cursor
        if not cursor or cursor in seen:
            raise ExternalServiceError(f'MCP server does not expose "{name}"', hint=_HINT)
        seen.add(cursor)


def _check_schema(tool: Tool, expected: list[str]) -> None:
    """The mapped names must exist, and nothing else may be required (G8, G18)."""
    schema = tool.input_schema
    props = schema.get("properties")
    actual = sorted(props) if isinstance(props, dict) else []
    required = schema.get("required")
    missing = [n for n in expected if n not in actual]
    unsent = [n for n in required if n not in expected] if isinstance(required, list) else []
    if not missing and not unsent:
        return
    message = (
        f'MCP tool "{tool.name}" arguments do not match: expected {", ".join(expected)}; '
        f"the server has {', '.join(actual) or 'none'}"
    )
    if unsent:
        message += f" and also requires {', '.join(map(str, unsent))}"
    raise ExternalServiceError(message, hint="set gmail_mcp.arg_names to the server's names")


def _parse_result(result: CallToolResult) -> DraftResult:
    """Draft ID and link from the structured content, else from JSON in the first text (G19)."""
    draft_id: str | None = None
    link: str | None = None
    for obj in (result.structured_content, _text_json(result)):
        if not isinstance(obj, dict):
            continue
        draft_id = draft_id or _draft_id(obj)
        link = link or next(
            (v for k in ("link", "url") if isinstance(v := obj.get(k), str) and v), None
        )
    if link is None and draft_id is not None:
        link = _LINK.format(quote(draft_id, safe=""))
    return DraftResult(draft_id, link, result.model_dump(mode="json", exclude_none=True))


def _draft_id(obj: Mapping[str, Any]) -> str | None:
    draft = obj.get("draft")
    nested = draft.get("id") if isinstance(draft, dict) else None
    for value in (obj.get("id"), obj.get("draftId"), nested):
        if isinstance(value, str | int) and not isinstance(value, bool) and str(value):
            return str(value)
    return None


def _text(result: CallToolResult) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.content if c.type == "text").strip()


def _text_json(result: CallToolResult) -> Any:
    first = next((c for c in result.content if c.type == "text"), None)
    try:
        return json.loads(getattr(first, "text", ""))
    except ValueError:
        return None


def _external_error(error: BaseException, timeout_s: float) -> BaseException:
    """The error `create_draft` raises for `error`: ours unchanged, anything external → exit 3."""
    leaf = _leaf(error)
    if isinstance(leaf, ActionTrackError) or not isinstance(leaf, Exception):
        return leaf  # our own errors, KeyboardInterrupt, cancellation
    if isinstance(leaf, TimeoutError):
        return ExternalServiceError(
            f"the Gmail MCP server timed out after {timeout_s:g} s", hint=_HINT
        )
    if isinstance(leaf, OSError):
        return ExternalServiceError(f"cannot reach the Gmail MCP server: {leaf}", hint=_HINT)
    return ExternalServiceError(
        f"the Gmail MCP call failed: {type(leaf).__name__}: {leaf}", hint=_HINT
    )


def _leaf(error: BaseException) -> BaseException:
    """The most telling exception inside (possibly nested) exception groups: ours first."""
    if not isinstance(error, BaseExceptionGroup):
        return error
    leaves = [_leaf(e) for e in error.exceptions]
    return next((e for e in leaves if isinstance(e, ActionTrackError)), leaves[0])
