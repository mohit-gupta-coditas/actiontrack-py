# M4 — Test Cases

Location: `tests/unit/parsing/test_items.py`. Notes are built in memory as `NoteMeta`. Meeting date Wed 2026-11-18. Default roster
[Priya Shah, Rahul Mehta].

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M4-01 | `- [ ] Priya to send the revised quote by Friday` | `extract_items` | 1 item: owner key priya.shah@…, task `send the revised quote`, due 2026-11-20, open | REQ-ITEM-01, 04, 05 |
| TC-M4-02 | `- [x] Rahul to book venue` | `extract_items` | `checked=True` | REQ-ITEM-01 |
| TC-M4-03 | `* [X] …` and `+ [ ] …` bullets | `extract_items` | Both detected | REQ-ITEM-01 |
| TC-M4-04 | `    - [ ] Priya will check numbers` (indented) | `extract_items` | Detected, task `check numbers` | REQ-ITEM-01, 04 |
| TC-M4-05 | `-[ ] Rahul to call` | `extract_items` | No item. Warning `MALFORMED_CHECKBOX` with the correct line no | REQ-ITEM-02 |
| TC-M4-06 | `- [] Rahul to call` | `extract_items` | Malformed warning | REQ-ITEM-02 |
| TC-M4-07 | `[ ] Rahul to call` (no bullet) | `extract_items` | Malformed warning | REQ-ITEM-02 |
| TC-M4-08 | `- [-] Rahul to call` | `extract_items` | Malformed warning | REQ-ITEM-02 |
| TC-M4-09 | `- [ ]` with no text | `extract_items` | Warning `EMPTY_TASK`, no item | REQ-ITEM-02 |
| TC-M4-10 | A checkbox inside a ```` ``` ```` fence, plus one after the fence | `extract_items` | Only the one after the fence is extracted | REQ-ITEM-03 |
| TC-M4-11 | `- [ ] Rahul Mehta: book venue` | `extract_items` | owner Rahul, task `book venue` | REQ-ITEM-04 |
| TC-M4-12 | `- [ ] Priya — draft the proposal` | `extract_items` | owner Priya, task `draft the proposal` | REQ-ITEM-04 |
| TC-M4-13 | `- [ ] Follow up with legal @rahul.mehta by Monday` | `extract_items` | owner Rahul, task `Follow up with legal`, due 2026-11-23 | REQ-ITEM-04, 05 |
| TC-M4-14 | `- [ ] send the deck to Rahul` | `extract_items` | owner None (lowercase start), task unchanged, `UNASSIGNED` | REQ-ITEM-04, 07 |
| TC-M4-15 | `- [ ] Update the onboarding doc` | `extract_items` | `{UNASSIGNED, NO_DUE}` | REQ-ITEM-07 |
| TC-M4-16 | `- [ ] Priya and Rahul to review contract EOW` | `extract_items` | owner Priya, `MULTI_OWNER` in flags, due 2026-11-20 | REQ-ITEM-06 |
| TC-M4-17 | `- [ ] Priya, Rahul to sync` | `extract_items` | owner Priya, `MULTI_OWNER` | REQ-ITEM-06 |
| TC-M4-18 | `- [ ] **Priya** to send [the deck](http://x) by Friday.` | `extract_items` | task `send the deck`, owner Priya | REQ-ITEM-05 |
| TC-M4-19 | `- [ ] Priya to by Friday` | `extract_items` | Warning `EMPTY_TASK`, no item | REQ-ITEM-05 |
| TC-M4-20 | Roster [Priya Shah, Priya Nair], `- [ ] Priya to send quote` | `extract_items` | owner key None, `AMBIGUOUS_OWNER`, candidates 2 | REQ-ITEM-04 (via M2) |
| TC-M4-21 | `- [ ] Rahul to fix it ASAP` | `extract_items` | task `fix it`, `UNPARSED_DUE`, due_raw `ASAP` | REQ-ITEM-05 (via M3) |
| TC-M4-22 | A note with 5 items and 2 malformed lines | `extract_items` | 5 items in line order, 2 warnings, line numbers match the file | REQ-ITEM-01, 02 |
| TC-M4-23 | `Some text mentioning [ ] brackets mid-line` | `extract_items` | Neither item nor warning | REQ-ITEM-01 |
