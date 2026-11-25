# M1 — Test Cases

Location: `tests/unit/parsing/test_note_loader.py`. Fixtures in `tests/fixtures/notes/loader/`, written to `tmp_path` where
bytes matter (BOM, CRLF, binary).

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M1-01 | Valid frontmatter note (date, title, 3 attendees, body) | `load_note` | `NoteMeta`: date 2026-11-18, title, 3 attendees in order | REQ-NOTE-01 |
| TC-M1-02 | Heading layout `# Q4 pricing sync — 2026-11-18` + `Attendees: A, B, C` | `load_note` | date parsed from H1, title `Q4 pricing sync`, 3 attendees | REQ-NOTE-02 |
| TC-M1-03 | Body `**Date:** 18 Nov 2026` with no frontmatter | `load_note` | date 2026-11-18 | REQ-NOTE-03 |
| TC-M1-04 | `## Attendees` heading + bullet list | `load_note` | attendees taken from the bullets | REQ-NOTE-02 |
| TC-M1-05 | `date: 03/04/2026`, DMY | `load_note` | 2026-04-03 | REQ-NOTE-03, REQ-DATE-06 |
| TC-M1-06 | Same, `date_order="MDY"` | `load_note` | 2026-03-04 | REQ-NOTE-03 |
| TC-M1-07 | No date anywhere | `load_note` | `SkipRecord(MISSING_DATE)` | REQ-NOTE-04 |
| TC-M1-08 | `date: sometime next week` | `load_note` | `SkipRecord(UNPARSEABLE_DATE)`, detail contains the raw value | REQ-NOTE-04 |
| TC-M1-09 | `date: 18 Nov` (no year) | `load_note` | `UNPARSEABLE_DATE` | REQ-NOTE-04 |
| TC-M1-10 | Valid date, no attendees in any form | `load_note` | `SkipRecord(MISSING_ATTENDEES)` | REQ-NOTE-05 |
| TC-M1-11 | `attendees: []` | `load_note` | `MISSING_ATTENDEES` | REQ-NOTE-05 |
| TC-M1-12 | Frontmatter with no closing `---` | `load_note` | `INVALID_FRONTMATTER` | REQ-NOTE-06 |
| TC-M1-13 | Frontmatter with a YAML syntax error on file line 4 | `load_note` | `INVALID_FRONTMATTER`, `line_no == 4` | REQ-NOTE-06 |
| TC-M1-14 | Frontmatter that is a YAML list, not a mapping | `load_note` | `INVALID_FRONTMATTER` | REQ-NOTE-06 |
| TC-M1-15 | 0-byte file, and a whitespace-only file | `load_note` | `EMPTY_FILE` for both | REQ-NOTE-06 |
| TC-M1-16 | Bytes containing `\x00` (e.g. a PNG renamed to .md) | `load_note` | `BINARY_FILE` | REQ-NOTE-06 |
| TC-M1-17 | Latin-1 bytes `0xE9` | `load_note` | `INVALID_ENCODING` | REQ-NOTE-06 |
| TC-M1-18 | Valid note with a UTF-8 BOM | `load_note` | Parses. The first frontmatter fence is recognised | REQ-NOTE-07 |
| TC-M1-19 | Valid note with CRLF line endings | `load_note` | Parses. No `\r` in any line text | REQ-NOTE-07 |
| TC-M1-20 | Frontmatter of 6 lines, checkbox on file line 12 | `load_note` | `lines` contains `(12, "- [ ] …")` | REQ-NOTE-01 |
| TC-M1-21 | `---` horizontal rule in the body, no frontmatter | `load_note` | Not treated as frontmatter | REQ-NOTE-02 |
| TC-M1-22 | Any valid note | `load_note` twice | Same `sha256`. File mtime and contents unchanged | REQ-GEN-03 |
| TC-M1-23 | Unreadable path (a directory, or a permission error via monkeypatch) | `load_note` | `READ_ERROR`, no exception | REQ-NOTE-06 |
| TC-M1-24 | 20k-line generated note | `load_note` | Completes in < 1 s | REQ-NOTE-01 |
