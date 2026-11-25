# M1 — Note Loader

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/parsing/note_loader.py` |
| **REQ IDs** | REQ-NOTE-01 … 07, REQ-GEN-03 |

## 1. Purpose
Turn one markdown file into either a `NoteMeta` (meeting date, title, raw attendees, numbered body lines) or a `SkipRecord`
explaining why the note is unusable. A pure function apart from reading the file. **It never raises for content problems.**

## 2. Interface

```python
def load_note(path: Path, *, date_order: Literal["DMY", "MDY"] = "DMY") -> NoteMeta | SkipRecord
def parse_meeting_date(text: str, *, date_order: Literal["DMY", "MDY"]) -> date | None   # reused by tests / M3
```

## 3. Processing rules (in order)

| Step | Rule | On failure |
|---|---|---|
| 1. Read | `path.read_bytes()`. The file is opened read-only and never written (REQ-GEN-03) | `OSError` → `READ_ERROR` (detail = the error message) |
| 2. Empty | 0 bytes, or only whitespace after decoding | `EMPTY_FILE` |
| 3. Binary | A NUL byte in the first 8 KiB | `BINARY_FILE` |
| 4. Decode | `utf-8-sig` (BOM removed) | `UnicodeDecodeError` → `INVALID_ENCODING` (detail = byte offset) |
| 5. Normalize | `\r\n` and `\r` → `\n` | — |
| 6. Hash | `sha256` of the **raw bytes** (before decode) | — |
| 7. Frontmatter | If line 1 is exactly `---` (trailing whitespace allowed): find the next line that is `---` or `...`. YAML-parse the block with `yaml.safe_load` | No closing fence, YAML error, or a result that isn't a mapping → `INVALID_FRONTMATTER`, `line_no` = the YAML error line (offset into the file) |
| 8. Body | All lines after the frontmatter (or every line if there is none), keeping the **original file line numbers** | — |
| 9. Meeting date | The first one found from: (a) frontmatter `date` (a YAML date or a string); (b) a body line matching `^\s*\**date\**\s*:\s*(.+)$` (case-insensitive) before the first checkbox line; (c) the first H1 (`# …`) containing a date substring | No candidate → `MISSING_DATE`. Candidate but `parse_meeting_date` gives None → `UNPARSEABLE_DATE` (detail = the raw value) |
| 10. Title | Frontmatter `title`, else the H1 text with a leading `Meeting:` / `Notes:` label (case-insensitive) and the date and separators (`—`, `-`, `:`, `|`) removed, else None (G37) | — |
| 11. Attendees | The first one found from: (a) frontmatter `attendees` / `participants` (a list, or a string split on `,`/`;`); (b) a body line `Attendees:` / `Participants:` (case-insensitive, optional bold) with a `,`/`;` list; (c) a heading `## Attendees` / `## Participants` followed by a bullet list (ends at the next heading or a blank line after the bullets). Entries are trimmed, empties dropped, order kept | No non-empty entry → `MISSING_ATTENDEES` |

### `parse_meeting_date`
1. If the text contains an ISO date `\d{4}-\d{2}-\d{2}` → `date.fromisoformat`.
2. Else `dateparser.parse` (lazy import) with `{"STRICT_PARSING": True, "DATE_ORDER": date_order, "PREFER_DAY_OF_MONTH": "first",
   "REQUIRE_PARTS": ["day", "month", "year"], "PARSERS": ["absolute-time"]}`, so a meeting date must have day, month
   **and** year. Relative words (`today`, `tomorrow`, `in 2 days`) are rejected: they would tie the date to the run's clock.
3. Return `date` or None. Never raises.

## 4. Edge cases
- Frontmatter `date: 2026-11-18` comes back from YAML as a `date`. A quoted string is parsed. A datetime → `.date()`.
- `date:` present in the frontmatter but empty → `MISSING_DATE`.
- A frontmatter `attendees` value that is a single string `"Priya Shah, Rahul"` → split.
- `---` horizontal rules later in the body are not frontmatter (only line 1 counts).
- Very long files (>10k lines) are processed line by line. No regex over the whole file at once.
- Body line numbers must match the line numbers an editor shows for the original file, including the frontmatter offset.

## 5. Out of scope
Parsing attendee names/emails (M2). Detecting action items (M4).

## 6. Open questions
None.
