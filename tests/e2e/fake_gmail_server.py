"""A fake Gmail MCP server over stdio, for the M12 e2e tests (T12.3).

It exposes `create_draft` next to the tools that must never be called (`send_message`, `reply`,
`forward`), reusing the M10 tool definitions, and appends every call it receives to the JSON
file named by the first argument, so the test can read it after the CLI exits.

    python tests/e2e/fake_gmail_server.py <calls.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.integration.mcp_fakes import FORBIDDEN, schema, text_result

DRAFT = {"id": "r-e2e-1", "threadId": "t-e2e-1", "viewUrl": "https://mail.example/drafts/r-e2e-1"}


def build_server(log_path: Path) -> Server[Any]:
    tools = [types.Tool(name=n, input_schema=schema("to", "subject", "body")) for n in FORBIDDEN]
    tools.append(
        types.Tool(
            name="create_draft",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        )
    )

    async def list_tools(
        _ctx: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def call_tool(_ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        calls = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        calls.append({"name": params.name, "arguments": dict(params.arguments or {})})
        log_path.write_text(json.dumps(calls), encoding="utf-8")
        return text_result(json.dumps(DRAFT), structured=DRAFT)

    return Server("fake-gmail-stdio", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(log_path: Path) -> None:
    server = build_server(log_path)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(serve, Path(sys.argv[1]))
