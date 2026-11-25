# M9 — Test Cases

Location: `tests/unit/email/test_render.py`. Snapshots in `tests/unit/email/snapshots/*.txt` (compared exactly). Today 2026-11-25.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M9-01 | 2 overdue + 3 open (one with no due) | `render_followup` | Body equals snapshot `mixed.txt` | REQ-FU-04 |
| TC-M9-02 | Same as 01 | subject | `Follow-up: your open action items (3 open, 2 overdue)` | REQ-FU-04 |
| TC-M9-03 | 0 overdue, 2 open | `render_followup` | No `Overdue` section. Subject `(2 open)` | REQ-FU-04 |
| TC-M9-04 | 2 overdue, 0 open | `render_followup` | No `Open` section. Subject `(0 open, 2 overdue)` | REQ-FU-04 |
| TC-M9-05 | Both empty | `render_followup` | `ValueError` | REQ-FU-04 |
| TC-M9-06 | Overdue items due 11-20 and 11-10 given in that order | `render_followup` | 11-10 listed first. `15 days overdue` / `5 days overdue` | REQ-FU-04 |
| TC-M9-07 | Overdue by exactly 1 day | `render_followup` | `1 day overdue` | REQ-FU-04 |
| TC-M9-08 | Open item with no due + one with a due | `render_followup` | The dated one first. `no due date` text | REQ-FU-04 |
| TC-M9-09 | Item with `meeting_title=None` | `render_followup` | `From: Meeting, 2026-11-18` | REQ-FU-04 |
| TC-M9-10 | Same inputs | render 2× | Identical subject + body bytes | REQ-FU-04 |
| TC-M9-11 | Any output | — | No line ends with whitespace. Body ends with exactly one `\n`. Contains `sign_off` | REQ-FU-04 |
| TC-M9-12 | Task containing `{{ x }}` and `<b>` | `render_followup` | Rendered literally (no template injection, no escaping) | REQ-FU-04 |
