# M5 — Dedup & Item IDs

| | |
|---|---|
| **Status** | Draft |
| **Depends on** | M0 (types). Consumes `ParsedItem` (from M4) and `ExistingItem` (from M6) |
| **Files** | `actiontrack/dedup.py` |
| **REQ IDs** | REQ-DEDUP-01 … 06, REQ-ID-01, REQ-ID-02 |

## 1. Purpose
Group every parsed source (each checkbox occurrence across all notes) into unique action items, decide each group's merged
fields, and give it a stable ID. A **pure** function: the same inputs always produce the same output.

## 2. Interface

```python
@dataclass(frozen=True)
class DedupConfig:
    fuzzy_enabled: bool = True
    threshold: int = 88
    scorer: Callable[[str, str], float] | None = None   # default rapidfuzz.fuzz.token_set_ratio; injectable for tests

@dataclass(frozen=True)
class DedupResult:
    groups: tuple[ItemGroup, ...]
    decisions: tuple[MergeDecision, ...]
    orphaned_ids: tuple[str, ...]          # existing ids that matched no source

def normalize_task(task: str) -> str
def make_item_id(owner_key: str | None, task_norm: str) -> str        # 40-hex sha1
def group_items(sources: Sequence[ParsedItem], existing: Sequence[ExistingItem], cfg: DedupConfig) -> DedupResult
def shortest_unique_prefixes(ids: Iterable[str], *, min_len: int = 6) -> dict[str, str]
def resolve_prefix(prefix: str, ids: Iterable[str]) -> str            # UserInputError on <4 chars / no match / ambiguity
```

## 3. Normalization (REQ-DEDUP-01)
1. NFKC, casefold.
2. Replace any character that is not `[\w\s]` with a space.
3. Remove the stop-words `the`, `a`, `an`.
4. Collapse whitespace and trim.

`"Send the revised Quote!"` → `send revised quote`. Digits are kept (`v2` ≠ `v3`).

## 4. Grouping algorithm (REQ-DEDUP-02 … 04)

Sources are processed in the deterministic order `(meeting_date, str(note_path), line_no)`.

```
groups = []                       # each: owner_key, canonical_norm (first member), norms set, members, existing_id?
for each source s:
    n = normalize_task(s.task); k = s.owner.owner_key
    1. EXACT: a group with same k (None == None allowed) and n ∈ group.norms        → join, decision(kind=exact, score=100)
    2. FUZZY (only if cfg.fuzzy_enabled and k is not None):
         best = max over groups with same k of scorer(n, group.canonical_norm)
         if best ≥ threshold → join best group (ties → earliest-created group), decision(kind=fuzzy, score=best)
    3. else → new group
```
- Comparing against the group's **canonical** norm (not every member) prevents chain merges (A≈B, B≈C, A≉C).
- Items with no owner can only merge exactly (REQ-DEDUP-04).
- Items with `AMBIGUOUS_OWNER` have `owner_key=None`. They merge exactly with each other only when their `candidates` are also equal.
  Internally a group's **identity** is the `owner_key`, or `?<sorted candidates joined by ,>` for an ambiguous owner, or `None`.
  The identity (not the bare `owner_key`) is what groups compare and what goes into `make_item_id`, so two ambiguous items with the
  same task but different candidates get different IDs.

**Existing items**: before the loop, each `ExistingItem` seeds an empty "shell" group with its `id`, `owner_key` and `task_norms`.
Shells take part in the exact and fuzzy steps (canonical = the alphabetically smallest of its `task_norms`) and keep their ID. Shells
are seeded in `id` order. A source that would otherwise start a new group joins the shell whose `id` equals the ID that new group would
get (this is how an ambiguous-owner item finds its shell, since `ExistingItem` has no candidates). A shell that gets no members (or has
no `task_norms`) goes into `orphaned_ids`, sorted (REQ-INGEST-04 is applied by M7/M6).

## 5. Merged fields (REQ-DEDUP-05)

| Field | Rule |
|---|---|
| `id` | The shell's existing ID if any, else `make_item_id(owner_key, canonical_norm)` (REQ-ID-01) |
| `task` / `task_norm` | From the first member (earliest) |
| `owner_display` / `owner_raw` | From the latest member |
| `due_date` / `due_raw` | From the member with the latest `meeting_date` that has a `due_date`. Ties → highest `line_no` (D8). If no member has a `due_date`, `due_raw` comes from the latest member with an (unparsed) phrase, e.g. `ASAP` |
| `status` | `done` if the existing item is done (any source), **or** any member is `checked`. Otherwise `open` |
| `done_source` / `done_at` | Kept from the existing item when it is done (`cli` or `note`). Else `note` with `done_at=None` if any member is checked |
| `flags` | Union of owner flags (`UNASSIGNED`, `AMBIGUOUS_OWNER`, `OWNER_NOT_ATTENDEE`, `MULTI_OWNER`) across members. `NO_DUE` only if no member has a due phrase. `UNPARSED_DUE` only if `due_date` is None and some member had an unparsed phrase |
| `first_seen` / `last_seen` | min / max member `meeting_date` |
| `sources` | All members, in processing order |

## 6. IDs (REQ-ID-01, REQ-ID-02)
- `make_item_id = sha1(f"{owner_key or '∅'}|{task_norm}".encode()).hexdigest()`.
- `shortest_unique_prefixes`: each ID's shortest prefix of at least 6 chars that is unique within the set (used for display).
- `resolve_prefix`: strip and lowercase; fewer than 4 chars or non-hex → `UserInputError`. No match → `UserInputError('no item with id "<p>"')`.
  More than one match → `UserInputError('id "<p>" matches N items', hint=<list of short ids>)`.

## 7. Decision log (REQ-DEDUP-06)
One `MergeDecision` for every source that **joined** a group that already had a member (the first source to land in an existing-item
shell is not a merge, so an unchanged re-ingest does not report every item as merged): `item_id`, `kind`, `score`, `source=(path, line)`,
`matched_task_norm`. M7 prints these with `-v`.

## 8. Out of scope
Persistence. Which items are shown or hidden.

## 9. Open questions
None.
