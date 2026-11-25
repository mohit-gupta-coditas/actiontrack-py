# M9 — Follow-up Email Rendering

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/email/render.py`, `actiontrack/templates/followup.txt.j2` |
| **REQ IDs** | REQ-FU-04 |

## 1. Purpose
Render the follow-up email for one person from their open and overdue items. The output is **deterministic**: the same inputs
give the same bytes (D5). No LLM, no I/O apart from loading the packaged template.

## 2. Interface

```python
@dataclass(frozen=True)
class EmailItem:
    short_id: str; task: str; due_date: date | None
    meeting_title: str | None; meeting_date: date        # most recent source

@dataclass(frozen=True)
class RenderedEmail:
    subject: str; body: str

def render_followup(*, first_name: str, overdue: Sequence[EmailItem], open_: Sequence[EmailItem],
                    today: date, sign_off: str) -> RenderedEmail
```
`overdue` and `open_` are already split by the caller (M11). Both may not be empty at once (the caller guarantees it, and
`ValueError` is raised otherwise). Every `overdue` item must have a `due_date` strictly before `today`, otherwise `ValueError`
(a caller bug, G13).

## 3. Subject
`Follow-up: your open action items (N open, M overdue)`, where N = `len(open_)` (not overdue) and M = `len(overdue)` (G7 ✅).
- Pluralisation is fixed ("1 open, 1 overdue" reads fine in both).
- If M == 0 → `Follow-up: your open action items (N open)`.

## 4. Body (plain text, `followup.txt.j2`)

```
Hi {{ first_name }},

Here is a summary of the action items assigned to you in recent meetings.

Overdue ({{ overdue|length }}):
- {{ task }} (due {{ due }}, {{ days }} day(s) overdue) [{{ short_id }}]
  From: {{ meeting_title or "Meeting" }}, {{ meeting_date }}

Open ({{ open|length }}):
- {{ task }} (due {{ due or "no due date" }}) [{{ short_id }}]
  From: {{ meeting_title or "Meeting" }}, {{ meeting_date }}

Could you reply with an update, or let me know if any of these should be reassigned or closed?

{{ sign_off }}
```
- An empty section is left out entirely.
- Sort order: overdue items by due date ascending (most overdue first), then short_id. Open items by due date ascending with no-due last,
  then short_id.
- Dates are in ISO format (`2026-11-20`). `days` = `(today - due).days`, with "day" singular when it is 1.
- The Jinja environment: `StrictUndefined`, `autoescape=False`, `trim_blocks=True`, `lstrip_blocks=True`, `keep_trailing_newline=True`.
  The template is loaded with `PackageLoader("actiontrack", "templates")`. Jinja is lazily imported.
- Line endings `\n`. No trailing whitespace on any line: after rendering, every line is right-stripped and the body ends with
  exactly one `\n`, so trailing spaces in `sign_off` or a task cannot leak through (G14). Nothing else is changed.

## 5. Out of scope
Recipient resolution, MCP (M10/M11).

## 6. Open questions
None. G7 (meaning of N), G12 (template name), G13 (invalid overdue item) and G14 (trailing whitespace) were confirmed with M9.
