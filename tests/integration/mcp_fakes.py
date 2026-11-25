"""In-process fake Gmail MCP servers for the M10 tests (M10 tests.md), and a fake sink for M11.

Every fake exposes `create_draft` next to the tools that must never be called (`send_message`,
`reply`, `forward`) and records each call it receives. Every fake built is kept in `FAKES`, so a
test-wide fixture can assert that no send tool was ever invoked (TC-M10-02).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp.types as types
from mcp import ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.server import Server

from actiontrack.config import McpConfig
from actiontrack.email.gmail_mcp import DraftResult

FORBIDDEN = ("send_message", "reply", "forward")

FAKES: list[FakeGmail] = []


def schema(*names: str, required: tuple[str, ...] | None = None) -> dict[str, Any]:
    """An object schema with string properties `names`, all required unless `required` is given."""
    return {
        "type": "object",
        "properties": {n: {"type": "string"} for n in names},
        "required": list(names if required is None else required),
    }


def text_result(
    text: str, *, structured: Any = None, is_error: bool = False
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=is_error,
    )


@dataclass
class FakeGmail:
    draft_schema: dict[str, Any] | None = field(
        default_factory=lambda: schema("to", "subject", "body")
    )
    result: types.CallToolResult = field(
        default_factory=lambda: text_result('{"id": "r-123"}', structured={"id": "r-123"})
    )
    delay: float = 0.0
    page_size: int | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        FAKES.append(self)

    @property
    def tools(self) -> list[types.Tool]:
        tools = [
            types.Tool(name=n, input_schema=schema("to", "subject", "body")) for n in FORBIDDEN
        ]
        if self.draft_schema is not None:  # None: the server has no create_draft
            tools.append(types.Tool(name="create_draft", input_schema=self.draft_schema))
        return tools

    def server(self) -> Server[Any]:
        async def list_tools(
            _ctx: Any, params: types.PaginatedRequestParams | None
        ) -> types.ListToolsResult:
            tools = self.tools
            if self.page_size is None:
                return types.ListToolsResult(tools=tools)
            start = int(params.cursor) if params and params.cursor else 0
            end = start + self.page_size
            return types.ListToolsResult(
                tools=tools[start:end], next_cursor=str(end) if end < len(tools) else None
            )

        async def call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
            self.calls.append((params.name, dict(params.arguments or {})))
            if self.delay:
                await anyio.sleep(self.delay)
            return self.result

        return Server("fake-gmail", on_list_tools=list_tools, on_call_tool=call_tool)

    def session_factory(self) -> Callable[[], AbstractAsyncContextManager[ClientSession]]:
        @asynccontextmanager
        async def open_session() -> AsyncIterator[ClientSession]:
            transport = InMemoryTransport(self.server())
            async with transport as (read, write), ClientSession(read, write) as session:
                yield session

        return open_session


@dataclass
class RecordingSink:
    """A fake `DraftSink` (M11): records each draft, then returns `result` or raises `error`."""

    result: DraftResult = field(
        default_factory=lambda: DraftResult("r-123", "https://mail.example/r-123", {})
    )
    error: Exception | None = None
    drafts: list[dict[str, str]] = field(default_factory=list)
    configs: list[McpConfig] = field(default_factory=list)

    def factory(self, cfg: McpConfig) -> RecordingSink:
        """Stands in for `GmailMcpDraftSink` as the `sink_factory`."""
        self.configs.append(cfg)
        return self

    def create_draft(self, *, to: str, subject: str, body: str) -> DraftResult:
        self.drafts.append({"to": to, "subject": subject, "body": body})
        if self.error is not None:
            raise self.error
        return self.result
