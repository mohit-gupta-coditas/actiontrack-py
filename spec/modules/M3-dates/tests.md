# M3 — Test Cases

Location: `tests/unit/parsing/test_dates.py`. The anchor is **Wed 2026-11-18** unless stated. Table-driven with `pytest.mark.parametrize`.

| TC | Given text | Anchor | Then (due_date / due_raw / flags) | REQ |
|---|---|---|---|---|
| TC-M3-01 | `send the revised quote by Friday` | Wed 11-18 | 2026-11-20 / `by Friday` / ∅ | REQ-DATE-01, 02, 03 |
| TC-M3-02 | `send quote by Friday` | **Fri 2026-11-20** | 2026-11-27 | REQ-DATE-03 |
| TC-M3-03 | `send quote by Monday` | Wed 11-18 | 2026-11-23 | REQ-DATE-03 |
| TC-M3-04 | `send quote by next Friday` | Wed 11-18 | 2026-11-27 | REQ-DATE-04 (G6) |
| TC-M3-05 | `deck EOD` | Wed 11-18 | 2026-11-18 / `EOD` | REQ-DATE-04 |
| TC-M3-06 | `deck EOW` | Wed 11-18 | 2026-11-20 | REQ-DATE-04 |
| TC-M3-07 | `deck EOW` | Sat 2026-11-21 | 2026-11-27 | REQ-DATE-04 |
| TC-M3-08 | `deck by next week` | Wed 11-18 | 2026-11-23 | REQ-DATE-04 |
| TC-M3-09 | `deck by end of month` | Wed 11-18 | 2026-11-30 | REQ-DATE-04 |
| TC-M3-10 | `deck by end of next week` | Wed 11-18 | 2026-11-27 | REQ-DATE-04 |
| TC-M3-11 | `deck by tomorrow` | Wed 11-18 | 2026-11-19 | REQ-DATE-04 |
| TC-M3-12 | `renew licence by 5 Jan` | Wed **2026-12-16** | 2027-01-05 (year rollover) | REQ-DATE-02 |
| TC-M3-13 | `renew by 12 Dec` | Wed 11-18 | 2026-12-12 | REQ-DATE-01, 02 |
| TC-M3-14 | `renew due 2026-12-01` | any | 2026-12-01 / `due 2026-12-01` | REQ-DATE-01 |
| TC-M3-15 | `renew by 03/04/2027`, DMY | any | 2027-04-03 | REQ-DATE-06 |
| TC-M3-16 | Same, MDY | any | 2027-03-04 | REQ-DATE-06 |
| TC-M3-17 | `work on the deck` | any | None / None / `{NO_DUE}` (no false `on` match) | REQ-DATE-01 |
| TC-M3-18 | `review on 3 Dec` | Wed 11-18 | 2026-12-03 | REQ-DATE-01 |
| TC-M3-19 | `fix it ASAP` | any | None / `ASAP` / `{UNPARSED_DUE}` | REQ-DATE-05 |
| TC-M3-20 | `ship by the blue moon` | any | None / `by the blue moon` / `{UNPARSED_DUE}`, span covers the phrase | REQ-DATE-05 |
| TC-M3-21 | `send quote` | any | None / None / `{NO_DUE}`, span None | REQ-DATE-05 |
| TC-M3-22 | `draft by Monday, review by Friday` | Wed 11-18 | Last phrase wins: 2026-11-20 / `by Friday` | REQ-DATE-01 |
| TC-M3-23 | `send quote by Friday.` | Wed 11-18 | Trailing `.` not part of `due_raw` | REQ-DATE-01 |
| TC-M3-24 | `parse_user_date("friday", today=Fri 11-20)` | — | 2026-11-20 (on or after) | REQ-DATE-02 |
| TC-M3-25 | `parse_user_date("nonsense", …)` | — | `UserInputError` with hint | REQ-DATE-05 |
| TC-M3-26 | `send quote by Friday` | Wed 11-18 | `text[span[0]:span[1]] == "by Friday"` | REQ-DATE-01 |
