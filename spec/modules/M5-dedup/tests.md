# M5 — Test Cases

Location: `tests/unit/test_dedup.py`. `ParsedItem`s are made with a builder `src(owner, task, meeting, line=1, due=None, checked=False, path="a.md")`.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M5-01 | `"Send the revised Quote!"` | `normalize_task` | `send revised quote` | REQ-DEDUP-01 |
| TC-M5-02 | `"Ship v2"` vs `"Ship v3"` | `normalize_task` | They differ | REQ-DEDUP-01 |
| TC-M5-03 | Same owner, tasks `Send revised quote.` and `send the revised quote` in 2 notes | `group_items` | 1 group, 2 sources, decision exact | REQ-DEDUP-02 |
| TC-M5-04 | Different owners, same task | `group_items` | 2 groups | REQ-DEDUP-02 |
| TC-M5-05 | Same owner, `send revised quote` / `send revised quote to client` | `group_items` | 1 group, decision fuzzy, score ≥ 88 | REQ-DEDUP-03 |
| TC-M5-06 | Same owner, `send revised quote` / `send revised invoice` | `group_items` | 2 groups | REQ-DEDUP-03 |
| TC-M5-07 | Same owner, `update doc` / `update docs page` | `group_items` | 2 groups (no false merge at the default threshold) | REQ-DEDUP-03 |
| TC-M5-08 | Stub scorer returning 87, threshold 88 | `group_items` | Not merged | REQ-DEDUP-03 |
| TC-M5-09 | Stub scorer returning 88, threshold 88 | `group_items` | Merged | REQ-DEDUP-03 |
| TC-M5-10 | `fuzzy_enabled=False`, pair from 05 | `group_items` | 2 groups | REQ-DEDUP-03 |
| TC-M5-11 | Both owner None, near-identical tasks | `group_items` | 2 groups. Identical tasks → 1 group | REQ-DEDUP-04 |
| TC-M5-12 | Stub scorer: A≈B 90, B≈C 90, A≈C 70. Order A, B, C | `group_items` | A+B in one group, C separate (no chaining) | REQ-DEDUP-03 |
| TC-M5-13 | Same item: note 11-04 due 11-07, note 11-18 due 11-20 | `group_items` | due 11-20, first_seen 11-04, last_seen 11-18 | REQ-DEDUP-05 |
| TC-M5-14 | Same item: note 11-04 due 11-07, note 11-18 with no due | `group_items` | due 11-07 (latest **with** a due), no `NO_DUE` | REQ-DEDUP-05 |
| TC-M5-15 | Same item checked in note 1, unchecked in note 2 (later) | `group_items` | status done, done_source note | REQ-DEDUP-05 |
| TC-M5-16 | Existing item done via cli. The sources are all unchecked | `group_items` | Keeps status done, done_source cli, the same id | REQ-DEDUP-05, REQ-ID-01 |
| TC-M5-17 | Existing item whose task_norm matches no source | `group_items` | Its id is in `orphaned_ids` | REQ-DEDUP-05 |
| TC-M5-18 | Same sources shuffled | `group_items` twice | Identical `groups` (ids, fields, source order) | REQ-ID-01 |
| TC-M5-19 | New group | `make_item_id(k, n)` | Equals `sha1("k|n")`. `None` owner uses `∅` | REQ-ID-01 |
| TC-M5-20 | ids `abc123ff…`, `abc124ee…` | `shortest_unique_prefixes` | Both 6 chars. With `abc123ff…`/`abc123fe…` → 8 chars | REQ-ID-02 |
| TC-M5-21 | ids as above | `resolve_prefix("abc12")` | `UserInputError` "matches 2 items" with hint | REQ-ID-02 |
| TC-M5-22 | — | `resolve_prefix("ab")`, `resolve_prefix("zzzz")`, `resolve_prefix("xyz!")` | `UserInputError` each | REQ-ID-02 |
| TC-M5-23 | — | `resolve_prefix("ABC123")` | Case-insensitive match | REQ-ID-02 |
| TC-M5-24 | 3 sources joining groups | `group_items` | 3 decisions with kind, score, source, matched norm | REQ-DEDUP-06 |
| TC-M5-25 | Two `AMBIGUOUS_OWNER` items, same task, different candidate sets | `group_items` | 2 groups | REQ-DEDUP-04 |
