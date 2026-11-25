# M3 — Due-Date Extraction & Resolution

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/parsing/dates.py` |
| **REQ IDs** | REQ-DATE-01 … 06 |

## 1. Purpose
Find the due phrase in an action item's text, and resolve it to a real date **anchored on the meeting date**, using
deterministic rules. Also parse user-supplied dates for `list --due-before`.

## 2. Interface

```python
def extract_due(text: str, *, anchor: date, date_order: Literal["DMY", "MDY"] = "DMY") -> DueResolution
    # DueResolution.span → the char range to remove from the text when building the task (M4)
def resolve_expr(expr: str, *, anchor: date, date_order: Literal["DMY", "MDY"] = "DMY") -> date | None
def parse_user_date(text: str, *, today: date, date_order: Literal["DMY", "MDY"] = "DMY") -> date
    # raises UserInputError on failure; anchored on today
```

## 3. Phrase detection (REQ-DATE-01)

Searched case-insensitively. When several phrases match, the **last** one in the text wins (due phrases are usually at the end).

| Kind | Pattern (simplified) | Example |
|---|---|---|
| Connector + expression | `\b(by|before|due(?: on| by)?|until|no later than|deadline:?)\s+<expr>` | `by Friday`, `due 12 Dec` |
| `on` + date-like expression only | `\bon\s+<datelike>` where datelike starts with a weekday, a month name or a digit | `on 3 Dec`. **Not** `work on the deck` |
| Standalone keyword | `\b(EOD|EOW|EOM|end of (?:the )?(day|week|month)|end of next week|tomorrow|today|next week|ASAP)\b` | `send deck EOW` |
| Bare ISO date | `\b\d{4}-\d{2}-\d{2}\b` | `ship 2026-12-01` |

`<expr>` runs to the end of the text, or to the first `,` `;` `(` or ` - `, with trailing `.`/`!` removed.
`due_raw` = the matched phrase as written (e.g. `by Friday`).

Overlapping matches: a keyword, bare ISO date or `on` phrase that ends where a longer phrase ends is part of that phrase
and is not a candidate itself. So `by tomorrow`, `by end of next week`, `due 2026-12-01` and `due on 3 Dec` are kept
whole, while in `follow up on Monday's notes by Friday` the later `by Friday` wins. A connector expression runs to the
end of the text, so `by Monday then ship tomorrow` is one phrase, and it is unresolvable.

## 4. Resolution rules (REQ-DATE-02 … 06)

Relative keywords are handled by **our own rules** (deterministic). Only absolute/calendar expressions go to `dateparser`.
In the table, A is the meeting date.

| Expression | Result |
|---|---|
| `today`, `EOD`, `end of day` | A |
| `tomorrow` | A + 1 |
| `<weekday>` / `this <weekday>` | First occurrence **strictly after** A (A is Friday and the text says Friday → A + 7) (REQ-DATE-03) |
| `next <weekday>` | That weekday in the calendar week after A's week (Mon-start) (gap G6) |
| `EOW`, `end of (the) week` | Friday of A's week. If A is Fri/Sat/Sun → the following Friday |
| `end of next week` | Friday of the week after A's week |
| `next week` | Monday of the week after A's week |
| `EOM`, `end of (the) month` | Last day of A's month |
| ISO `YYYY-MM-DD` | That date (no anchoring) |
| `12 Dec`, `Dec 12`, `12th December` (no year) | The first occurrence **on or after A**, so a December meeting saying `5 Jan` gives next year |
| `12 Dec 2026`, `12/12/2026`, `03/04/2026` | Absolute. Numeric dates follow `date_order` (REQ-DATE-06) |
| `3/4` (numeric, no year) | Day/month per `date_order`, first occurrence on or after A |
| `ASAP`, or anything else unresolvable | None (gap G9) |

`dateparser` settings: `RELATIVE_BASE=datetime.combine(A, time())`, `PREFER_DATES_FROM="future"`, `DATE_ORDER=date_order`,
`STRICT_PARSING=False`, `RETURN_TIME_AS_PERIOD=False`. Lazily imported.

- Only an expression that has a numeric date (`3/4`, `03/04/2027`) or a month name plus a digit (`12 Dec`) goes to
  `dateparser`. Anything else (`the blue moon`, `12`, `the team`) is unresolvable without calling it.
- Without a year, `dateparser`'s `future` skips the anchor day itself (`18 Nov` said on 18 Nov gives next year). So for a
  year-less date only the day and month are taken from it, and the year is the first one where the date is on or after A
  (`29 Feb` → the next leap year).
- Weekday names accept the usual abbreviations (`Mon`, `Tues`, `Thurs`, ...).

## 5. Flags (REQ-DATE-05)
- No phrase found → `due_date=None`, `due_raw=None`, flags `{NO_DUE}`, span None.
- Phrase found but unresolvable → `due_date=None`, `due_raw=<phrase>`, flags `{UNPARSED_DUE}`, span set (the phrase is still
  removed from the task text).
- Phrase found and resolved → no flags.

## 6. `parse_user_date`
Used by `list --due-before`. The same rules with `anchor=today`, except `<weekday>` means the next occurrence **on or after**
today. Unresolvable → `UserInputError('could not understand date "<text>"', hint="use YYYY-MM-DD")`.

## 7. Out of scope
Removing owner/connector text (M4).

## 8. Open questions
G6 (`next <weekday>`), G9 (`ASAP`). See plan §5.
