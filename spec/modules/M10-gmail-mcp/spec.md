# M10 — Gmail MCP Adapter

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/email/gmail_mcp.py`, `actiontrack/email/outbox.py` |
| **REQ IDs** | REQ-MCP-01 … 05, REQ-GEN-01 |

## 1. Purpose
Create a Gmail **draft** through the Gmail MCP connector, acting as an MCP client. The adapter can only create drafts.
Sending is impossible by construction (REQ-GEN-01).

## 2. Interface

```python
@dataclass(frozen=True)
class DraftResult:
    draft_id: str | None; link: str | None; raw: Mapping[str, Any]

class DraftSink(Protocol):
    def create_draft(self, *, to: str, subject: str, body: str) -> DraftResult: ...

ALLOWED_TOOLS: Final = frozenset({"create_draft"})     # module constant; the configured draft_tool must be in it

class GmailMcpDraftSink:                                # implements DraftSink
    def __init__(self, cfg: McpConfig, *, session_factory: SessionFactory | None = None) -> None
    def create_draft(self, *, to: str, subject: str, body: str) -> DraftResult
    # no other public methods; no generic call_tool exposed (REQ-MCP-03)

def write_outbox(*, outbox_dir: Path, owner_key: str, to: str, subject: str, body: str, now: datetime) -> Path
```
`SessionFactory` is a zero-argument callable returning an async context manager that yields a connected (not yet initialized)
`mcp.ClientSession`. It is injectable so tests can use an in-memory fake server.

**SDK** (G16): the adapter targets the `mcp` 2.x SDK (`mcp>=2.3,<3`). Its names are used throughout: `streamable_http_client`,
`mcp.server.mcpserver.MCPServer` (formerly `FastMCP`), and the snake_case fields `input_schema`, `structured_content`,
`is_error`, `next_cursor`.

## 3. Behaviour

**Construction** (REQ-MCP-01):
- `transport="stdio"` → `StdioServerParameters(command, args)` + `stdio_client`. `command` missing → `UserInputError` naming
  `gmail_mcp.command`.
- `transport="http"` → `streamable_http_client(url)`. `url` missing → `UserInputError`.
- `cfg.draft_tool not in ALLOWED_TOOLS` → `ForbiddenToolError` at construction (so config can't be used to point it at `send_message`).

**`create_draft`** (sync wrapper around async code, `anyio.run`, the whole call inside `anyio.fail_after(cfg.timeout_s)`):
1. Open the session and `initialize()`.
2. `list_tools()`, following `next_cursor` until the draft tool is found or the pages run out (G16) → the draft tool must be
   present (REQ-MCP-02). Missing → `ExternalServiceError('MCP server does not expose "create_draft"', hint="check gmail_mcp settings")`.
3. Validate the tool's `input_schema` (gap G8): `properties` must contain the mapped arg names (`cfg.arg_names`), and every name
   in `required` must be one of them (G18). Otherwise → `ExternalServiceError` listing the expected vs. actual names; no call is made.
4. Build the arguments: `{arg_names.to: [to] if to_as_list else to, arg_names.subject: subject, arg_names.body: body}`.
5. `self._call(tool_name, args)`. **`_call` checks `ALLOWED_TOOLS` first** and raises `ForbiddenToolError` for anything else (REQ-MCP-03).
6. Result `is_error` → `ExternalServiceError` with the text content.
7. Parse the draft ID: `structured_content.id` / `draftId` / `draft.id`, else a JSON object in the first text content with the same
   keys, else None (a non-string ID is converted with `str`). Link (G19, G21): a `viewUrl` / `link` / `url` string (in that order) when present,
   else `https://mail.google.com/mail/#drafts?compose=<id>` when an ID was found, else None.
8. Timeout, connection error, process launch failure, MCP protocol error → `ExternalServiceError` (exit 3) (REQ-MCP-04).
   Errors raised inside the SDK's task groups arrive as `ExceptionGroup`s and are unwrapped first. `ForbiddenToolError` is
   never converted.

**Credentials** (REQ-MCP-05): the adapter never reads, stores or logs tokens. Auth is entirely the server's job. Logs at DEBUG
show the tool name and argument **keys** only, never values.

**Outbox** (REQ-MCP-04): `write_outbox` writes an RFC 5322 `.eml` (`email.message.EmailMessage`, headers `To`, `Subject`, `Date`,
`X-Actiontrack-Status: draft-not-created`) to `outbox_dir/<owner-key-slug>-<YYYYMMDDTHHMMSS>.eml`. Slug (G17): the owner key
lowercased, each run of characters outside `[a-z0-9._-]` replaced by `-`, leading/trailing `-` and `.` trimmed, `unknown` if
empty (`priya.shah@coditas.com` → `priya.shah-coditas.com`, `name:priya` → `name-priya`). The timestamp and `Date` use `now` in
its own timezone. It creates the directory and
never overwrites an existing file (adds `-2`, `-3`…). M11 calls it when `create_draft` raises `ExternalServiceError`.

## 4. Out of scope
Rendering (M9). Deciding when to draft (M11). Installing or authenticating the MCP server.

## 5. Open questions
Q6 (answered, G20–G22): the server is the **Gmail MCP connector**. Its `create_draft` takes `to` (array), `subject`, `body`
(all optional; also `cc`, `bcc`, `htmlBody`, `attachments`, `includeSignature`) and returns `id`, `threadId`, `viewUrl`. The
defaults match it (`to_as_list = true`). The adapter stays auth-free: `[gmail_mcp]` points at an endpoint (http `url` or a
stdio bridge `command`) that already handles OAuth. The exact endpoint is confirmed in M12's manual smoke test.
