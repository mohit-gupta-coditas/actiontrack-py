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
`SessionFactory` is an async context manager that yields a connected `mcp.ClientSession`. It is injectable so tests can use an
in-memory fake server.

## 3. Behaviour

**Construction** (REQ-MCP-01):
- `transport="stdio"` → `StdioServerParameters(command, args)` + `stdio_client`. `command` missing → `UserInputError` naming
  `gmail_mcp.command`.
- `transport="http"` → `streamablehttp_client(url)`. `url` missing → `UserInputError`.
- `cfg.draft_tool not in ALLOWED_TOOLS` → `ForbiddenToolError` at construction (so config can't be used to point it at `send_message`).

**`create_draft`** (sync wrapper around async code, `anyio.run`, the whole call inside `anyio.fail_after(cfg.timeout_s)`):
1. Open the session and `initialize()`.
2. `list_tools()` → the draft tool must be present (REQ-MCP-02). Missing → `ExternalServiceError('MCP server does not expose
   "create_draft"', hint="check gmail_mcp settings")`.
3. Validate that the tool's `inputSchema.properties` contains the mapped arg names (`cfg.arg_names`). Missing → `ExternalServiceError`
   listing the expected vs. actual names (gap G8).
4. Build the arguments: `{arg_names.to: [to] if to_as_list else to, arg_names.subject: subject, arg_names.body: body}`.
5. `self._call(tool_name, args)`. **`_call` checks `ALLOWED_TOOLS` first** and raises `ForbiddenToolError` for anything else (REQ-MCP-03).
6. Result `isError` → `ExternalServiceError` with the text content.
7. Parse the draft ID: `structuredContent.id` / `draftId` / `draft.id`, else a JSON object in the first text content with the same keys,
   else None. Link = `https://mail.google.com/mail/#drafts?compose=<id>` when an ID was found.
8. Timeout, connection error, process launch failure → `ExternalServiceError` (exit 3) (REQ-MCP-04).

**Credentials** (REQ-MCP-05): the adapter never reads, stores or logs tokens. Auth is entirely the server's job. Logs at DEBUG
show the tool name and argument **keys** only, never values.

**Outbox** (REQ-MCP-04): `write_outbox` writes an RFC 5322 `.eml` (`email.message.EmailMessage`, headers `To`, `Subject`, `Date`,
`X-Actiontrack-Status: draft-not-created`) to `outbox_dir/<owner-key-slug>-<YYYYMMDDTHHMMSS>.eml`. It creates the directory and
never overwrites an existing file (adds `-2`, `-3`…). M11 calls it when `create_draft` raises `ExternalServiceError`.

## 4. Out of scope
Rendering (M9). Deciding when to draft (M11). Installing or authenticating the MCP server.

## 5. Open questions
Q6/G8: the real Gmail MCP server's command/URL and `create_draft` argument schema need to be confirmed before M12's manual smoke test.
