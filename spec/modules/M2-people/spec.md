# M2 — People & Owner Resolution

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 |
| **Files** | `actiontrack/parsing/people.py` |
| **REQ IDs** | REQ-PEOPLE-01 … 06 |

## 1. Purpose
Parse the raw attendee strings of a note into `Attendee`s, build a per-note **roster**, resolve a raw owner string from an
action item to a canonical person key (handling two people with the same first name), and derive company email addresses.

## 2. Interface

```python
def parse_attendee(raw: str, *, domain: str) -> Attendee | None
def derive_email(full_name: str, *, domain: str) -> str          # raises UserInputError if there is no last name
def normalize_name(s: str) -> str                                 # casefold + strip accents + collapse spaces

class Roster:
    def __init__(self, attendees: Sequence[Attendee], *, domain: str) -> None
    attendees: tuple[Attendee, ...]
    def resolve(self, owner_raw: str | None) -> OwnerResolution

def build_roster(attendees_raw: Iterable[str], *, domain: str) -> Roster
```

## 3. Attendee parsing (REQ-PEOPLE-01)

Accepted forms (surrounding whitespace, `*`/`_` emphasis and a trailing role in parentheses such as `(PM)` are removed):

| Raw | full_name | email |
|---|---|---|
| `Priya Shah <priya.shah@coditas.com>` | Priya Shah | priya.shah@coditas.com |
| `Priya Shah (priya.shah@coditas.com)` | Priya Shah | priya.shah@coditas.com |
| `priya.shah@coditas.com` | Priya Shah (from the local part: split on `.`/`_`, title-cased) | priya.shah@coditas.com |
| `Priya Shah` | Priya Shah | None |
| `Priya` | Priya | None |
| `@priya.shah` | Priya Shah | None (handle) |
| empty / only punctuation | → None (dropped) | |

- `first_name` = the first token. `last_name` = the remaining tokens joined with a space, or None.
- `derived_email` = `derive_email(full_name)` when there is a last name, else None.
- **Key** (REQ-PEOPLE-05): explicit email lowercased → else `derived_email` → else `name:<normalize_name(first_name)>` (gap G1).
- Duplicate entries for the same key within one note are merged, keeping the one with an explicit email.

## 4. Email derivation (REQ-PEOPLE-06)
1. NFKD-normalize and drop combining marks (`López` → `Lopez`). Lowercase.
2. Remove apostrophes (`O'Brien` → `obrien`).
3. Split on whitespace and hyphens. Drop empty parts and any characters outside `[a-z0-9]`.
4. Fewer than 2 parts → `UserInputError('cannot derive email: no last name for "<name>"')`.
5. Join the parts with `.` and append `@<domain>`. Example: `Anna-Maria López` → `anna.maria.lopez@coditas.com`.

## 5. Owner resolution (REQ-PEOPLE-02 … 04)

`Roster.resolve(owner_raw)`: `owner_raw` is the name text M4 extracted (may start with `@`). Matching uses `normalize_name`.

| Order | Rule | Result |
|---|---|---|
| 0 | `owner_raw` is None or empty | key None, flags `{UNASSIGNED}` |
| 1 | Looks like an email, or an `@handle` equal to an attendee's email local part or derived-email local part | That attendee |
| 2 | Equals an attendee's full name | That attendee |
| 3 | `First L` / `First L.` and exactly one attendee has that first name + a last name starting with L | That attendee |
| 4 | A single token equal to the first name of **exactly one** attendee | That attendee |
| 4b | A single token equal to the first name of **2+ attendees** | key None, flags `{AMBIGUOUS_OWNER}`, `candidates` = their keys, sorted (REQ-PEOPLE-03) |
| 5 | A full name (2+ tokens) not in the roster | key = `derive_email(owner_raw)`, display = owner_raw, flags `{OWNER_NOT_ATTENDEE}` (REQ-PEOPLE-04) |
| 6 | A single token not in the roster | key None, flags `{OWNER_NOT_ATTENDEE, UNASSIGNED}` (gap G5) |

`owner_display` = the attendee's `full_name` (or `owner_raw` for rule 5). `owner_raw` is always kept as written.

## 6. Edge cases
- `Priya S.` with Priya Shah and Priya Nair → Priya Shah (rule 3).
- `priya` lowercase → matches case-insensitively.
- `José` vs `Jose` → equal after normalization.
- The roster has one Priya, and the owner is `Priya Nair`, who isn't an attendee → rule 5, not rule 4.
- Two attendees with identical full names and no emails → treated as the same person (same derived key).
- Rules 1–4 use the same pick: one distinct key → that attendee; 2+ distinct keys → `{AMBIGUOUS_OWNER}` with the
  sorted keys as `candidates` (e.g. `@ps` matching `ps@a.com` and `ps@b.com`, or two `Priya Shah`s with different emails).
- An email owner that matches no attendee → key = the email lowercased, display = owner text, `{OWNER_NOT_ATTENDEE}`.
- An `@handle` that matches no local part falls through to rules 2–6 with the handle read as a name
  (`@rahul` → `Rahul`, `@vikram.rao` → `Vikram Rao`).
- `First L.` where no attendee matches → key None, `{OWNER_NOT_ATTENDEE, UNASSIGNED}`. An initial is not a last name,
  so no email is derived from it (rule 5 does not apply).
- A multi-token owner whose email can't be derived (`Vikram ???`) → treated like rule 6.
- A first-name-only attendee `Priya` matches the owner `Priya` by full name (rule 2), so a roster of `Priya` and
  `Priya Shah` resolves `Priya` to `name:priya`, not to an ambiguity.
- Only entries with the same key merge. `Priya Shah` and `Priya Shah <ps@client.com>` in one note stay two attendees
  (a variant of gap G10).

## 7. Out of scope
Finding the owner text inside an item line (M4). Cross-note aliasing (future `people.yaml`, gap G10).

## 8. Open questions
G1 (`name:` key for first-name-only attendees), G5 (unknown single-token owner), G10 (two keys for one person). See plan §5.
