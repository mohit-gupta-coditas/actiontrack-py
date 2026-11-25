# M2 — Test Cases

Location: `tests/unit/parsing/test_people.py`. Domain `coditas.com` unless stated.

| TC | Given | When | Then | REQ |
|---|---|---|---|---|
| TC-M2-01 | `Priya Shah <Priya.Shah@Coditas.com>` | `parse_attendee` | full Priya Shah, email lowercased in key `priya.shah@coditas.com` | REQ-PEOPLE-01, 05 |
| TC-M2-02 | `Priya Shah (priya.shah@coditas.com)` | `parse_attendee` | Same as 01 | REQ-PEOPLE-01 |
| TC-M2-03 | `rahul.mehta@coditas.com` | `parse_attendee` | full `Rahul Mehta`, email kept | REQ-PEOPLE-01 |
| TC-M2-04 | `**Rahul Mehta** (PM)` | `parse_attendee` | full `Rahul Mehta`, key derived `rahul.mehta@coditas.com` | REQ-PEOPLE-01 |
| TC-M2-05 | `Priya` | `parse_attendee` | last None, derived None, key `name:priya` | REQ-PEOPLE-01, 05 |
| TC-M2-06 | `  ,, ` | `parse_attendee` | None | REQ-PEOPLE-01 |
| TC-M2-07 | `Anna-Maria López` | `derive_email` | `anna.maria.lopez@coditas.com` | REQ-PEOPLE-06 |
| TC-M2-08 | `Seán O'Brien` | `derive_email` | `sean.obrien@coditas.com` | REQ-PEOPLE-06 |
| TC-M2-09 | `Priya` | `derive_email` | `UserInputError` with `no last name for "Priya"` | REQ-PEOPLE-06 |
| TC-M2-10 | domain `example.org` | `derive_email("Rahul Mehta")` | `rahul.mehta@example.org` | REQ-PEOPLE-06 |
| TC-M2-11 | Roster [Priya Shah, Rahul Mehta] | `resolve("Priya")` | key `priya.shah@coditas.com`, no flags | REQ-PEOPLE-02 |
| TC-M2-12 | Roster [Priya Shah, Priya Nair] | `resolve("Priya")` | key None, `{AMBIGUOUS_OWNER}`, candidates both keys sorted | REQ-PEOPLE-03 |
| TC-M2-13 | Same roster | `resolve("Priya Nair")` | key `priya.nair@coditas.com` | REQ-PEOPLE-02 |
| TC-M2-14 | Same roster | `resolve("Priya S.")` | Priya Shah | REQ-PEOPLE-02 |
| TC-M2-15 | Roster with `Priya Shah <ps@client.com>` | `resolve("@ps")` | key `ps@client.com` | REQ-PEOPLE-02 |
| TC-M2-16 | Roster [Priya Shah] | `resolve("@priya.shah")` | Priya Shah (matches the derived local part) | REQ-PEOPLE-02 |
| TC-M2-17 | Roster [José Pérez] | `resolve("jose")` | José Pérez | REQ-PEOPLE-02 |
| TC-M2-18 | Roster [Priya Shah] | `resolve("Vikram Rao")` | key `vikram.rao@coditas.com`, `{OWNER_NOT_ATTENDEE}` | REQ-PEOPLE-04 |
| TC-M2-19 | Roster [Priya Shah] | `resolve("Vikram")` | key None, `{OWNER_NOT_ATTENDEE, UNASSIGNED}`, raw `Vikram` | REQ-PEOPLE-04 |
| TC-M2-20 | Any roster | `resolve(None)` and `resolve("")` | key None, `{UNASSIGNED}` | REQ-PEOPLE-02 |
| TC-M2-21 | Raw list has `Priya Shah` and `Priya Shah <priya.shah@coditas.com>` | `build_roster` | One attendee, with the explicit email | REQ-PEOPLE-01 |
| TC-M2-22 | Roster [Priya (first only), Rahul Mehta] | `resolve("Priya")` | key `name:priya`, no flags | REQ-PEOPLE-05 |
| TC-M2-23 | Roster [Priya Shah, Priya Nair] | `resolve("Priya N")` and `resolve("priya n.")` | Priya Nair | REQ-PEOPLE-02 |
