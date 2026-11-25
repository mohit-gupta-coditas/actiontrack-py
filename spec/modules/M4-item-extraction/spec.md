# M4 — Action Item Extraction

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M1 (`NoteMeta`), M2 (`Roster`), M3 (`extract_due`) |
| **Files** | `actiontrack/parsing/items.py` |
| **REQ IDs** | REQ-ITEM-01 … 07 |

## 1. Purpose
Walk the body lines of a loaded note, detect action items, and split each one into **owner / task / due**. The result is a list of
`ParsedItem` plus `LineWarning`s for malformed lines.

## 2. Interface

```python
def extract_items(note: NoteMeta, roster: Roster, *, date_order: Literal["DMY", "MDY"] = "DMY"
                  ) -> tuple[list[ParsedItem], list[LineWarning]]

# internal but tested directly
def classify_line(line: str) -> CheckboxLine | MalformedCheckbox | None
def split_owner(body: str) -> OwnerSplit       # (owner_raw | None, rest_without_owner_and_connector, multi_owner: bool)
def clean_inline_markdown(s: str) -> str
```

## 3. Line classification (REQ-ITEM-01 … 03)

1. **Code fences**: a line starting with ```` ``` ```` or `~~~` toggles "in fence". Lines inside a fence are ignored.
2. **Valid checkbox**: `^\s*[-*+]\s+\[( |x|X)\]\s+(?P<body>\S.*)$` → `CheckboxLine(checked = marker in "xX", body)`.
3. **Malformed checkbox** → `LineWarning(MALFORMED_CHECKBOX)`, the line is skipped:
   - `^\s*[-*+]\[[ xX]?\]` (no space after the bullet), e.g. `-[ ] Rahul …`
   - `^\s*[-*+]\s+\[\]` (empty brackets)
   - `^\s*\[[ xX]\]\s+\S` (no bullet)
   - `^\s*[-*+]\s+\[[^ xX\]]\]` (an unknown marker such as `[-]`, `[~]`, `[o]`)
   - `^\s*[-*+]\s+\[[ xX]\]\s*$` (a checkbox with no text) → code `EMPTY_TASK`
4. Anything else → None (ordinary text).

## 4. Splitting the body (REQ-ITEM-04 … 07)

Apply to `clean_inline_markdown(body)`. This strips `**`, `__`, `*`, `_`, and backticks used as emphasis, turns `[text](url)` into `text`,
and collapses whitespace.

**Owner** (`split_owner`):
1. **Leading name + connector**: `^(?P<owner>@?[\w.'-]+(?:\s+[\w.'-]+){0,2}?)\s*(?P<conn>:|—|–| - |\s+(?:to|will|should|must|needs to|is to|to\s+be)\b)\s*(?P<rest>.+)$`.
   The owner tokens must start with an uppercase letter or `@` (so `send the deck to Rahul` does not match).
2. **Multi-owner**: `A and B`, `A & B`, `A, B` before the connector → owner = A, `multi_owner=True` (REQ-ITEM-06).
3. **`@mention` anywhere** (only if rule 1 didn't match): the first `@handle` → owner = handle. The mention is removed from the text.
4. Otherwise owner_raw = None.

**Due**: `extract_due(rest, anchor=note.meeting_date)` (M3). The phrase at `span` is removed from `rest`.

**Task**: what's left of `rest`, trimmed of surrounding whitespace, `,;:-–—` and a trailing `.`. Original casing is kept.
Empty → `LineWarning(EMPTY_TASK)`, no item.

**Owner resolution**: `roster.resolve(owner_raw)` (M2).

**Flags**: `owner.flags | due.flags | ({MULTI_OWNER} if multi_owner)`. Items with no owner already carry `UNASSIGNED`, and items with no
due phrase already carry `NO_DUE` (REQ-ITEM-07).

## 5. Output
`ParsedItem(note_path, line_no, raw_text=<original line stripped>, meeting_date, note_title, owner, task, due, checked, flags)`,
in line order.

## 6. Examples

| Line | owner_raw | task | due_raw | flags |
|---|---|---|---|---|
| `- [ ] Priya to send the revised quote by Friday` | Priya | send the revised quote | by Friday | ∅ |
| `- [x] **Rahul Mehta**: book venue (due 2026-12-01)` | Rahul Mehta | book venue | due 2026-12-01 | ∅, checked |
| `- [ ] Update the onboarding doc` | — | Update the onboarding doc | — | UNASSIGNED, NO_DUE |
| `- [ ] Priya and Rahul to review contract EOW` | Priya | review contract | EOW | MULTI_OWNER |
| `- [ ] Follow up with legal @rahul.mehta by Monday` | @rahul.mehta | Follow up with legal | by Monday | ∅ |
| `  - [ ] Sub-task: Priya will check numbers` (nested) | Priya | check numbers | — | NO_DUE |

## 7. Out of scope
Normalization and dedup (M5). Persistence (M6).

## 8. Open questions
None (G5 is handled in M2).
