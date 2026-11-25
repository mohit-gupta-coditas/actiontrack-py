from __future__ import annotations

import pytest

from actiontrack.errors import UserInputError
from actiontrack.models import Attendee, Flag, OwnerResolution
from actiontrack.parsing.people import (
    Roster,
    build_roster,
    derive_email,
    normalize_name,
    parse_attendee,
)

DOMAIN = "coditas.com"


def attendee(raw: str, domain: str = DOMAIN) -> Attendee:
    result = parse_attendee(raw, domain=domain)
    assert result is not None, raw
    return result


def roster(*raw: str) -> Roster:
    return build_roster(raw, domain=DOMAIN)


def assert_resolved(res: OwnerResolution, key: str, display: str) -> None:
    assert res.owner_key == key
    assert res.owner_display == display
    assert res.flags == frozenset()
    assert res.candidates == ()


# --- parse_attendee ---------------------------------------------------------------------------


def test_TC_M2_01_name_with_angle_bracket_email() -> None:
    a = attendee("Priya Shah <Priya.Shah@Coditas.com>")
    assert a.full_name == "Priya Shah"
    assert a.first_name == "Priya"
    assert a.last_name == "Shah"
    assert a.email == "priya.shah@coditas.com"
    assert a.key == "priya.shah@coditas.com"
    assert a.derived_email == "priya.shah@coditas.com"


def test_TC_M2_02_name_with_parenthesised_email() -> None:
    assert attendee("Priya Shah (priya.shah@coditas.com)") == attendee(
        "Priya Shah <Priya.Shah@Coditas.com>"
    )


def test_TC_M2_03_bare_email_gives_name_from_local_part() -> None:
    a = attendee("rahul.mehta@coditas.com")
    assert a.full_name == "Rahul Mehta"
    assert a.email == "rahul.mehta@coditas.com"
    assert a.key == "rahul.mehta@coditas.com"
    assert attendee("anna_maria@client.com").full_name == "Anna Maria"


def test_TC_M2_04_emphasis_and_role_are_stripped() -> None:
    a = attendee("**Rahul Mehta** (PM)")
    assert a.full_name == "Rahul Mehta"
    assert a.email is None
    assert a.key == "rahul.mehta@coditas.com"
    assert attendee("_Rahul Mehta_").full_name == "Rahul Mehta"
    assert attendee("Rahul Mehta <rahul@client.com> (Client PM)").key == "rahul@client.com"


def test_TC_M2_05_first_name_only() -> None:
    a = attendee("Priya")
    assert a.full_name == "Priya"
    assert a.last_name is None
    assert a.derived_email is None
    assert a.email is None
    assert a.key == "name:priya"
    assert attendee("José").key == "name:jose"


@pytest.mark.parametrize("raw", ["  ,, ", "", "   ", "**", "()", "-"])
def test_TC_M2_06_empty_or_punctuation_is_dropped(raw: str) -> None:
    assert parse_attendee(raw, domain=DOMAIN) is None


def test_handle_attendee() -> None:
    a = attendee("@priya.shah")
    assert a.full_name == "Priya Shah"
    assert a.email is None
    assert a.key == "priya.shah@coditas.com"


def test_multi_word_last_name_and_whitespace_collapse() -> None:
    a = attendee("  Anna   Maria  López ")
    assert a.full_name == "Anna Maria López"
    assert a.first_name == "Anna"
    assert a.last_name == "Maria López"
    assert a.key == "anna.maria.lopez@coditas.com"


def test_last_name_with_no_derivable_letters_has_no_derived_email() -> None:
    a = attendee("Priya &")
    assert a.last_name == "&"
    assert a.derived_email is None
    assert a.key == "name:priya"


# --- derive_email / normalize_name ------------------------------------------------------------


def test_TC_M2_07_hyphen_and_accents() -> None:
    assert derive_email("Anna-Maria López", domain=DOMAIN) == "anna.maria.lopez@coditas.com"


def test_TC_M2_08_apostrophe_removed() -> None:
    assert derive_email("Seán O'Brien", domain=DOMAIN) == "sean.obrien@coditas.com"
    assert derive_email("Seán O\u2019Brien", domain=DOMAIN) == "sean.obrien@coditas.com"


def test_TC_M2_09_no_last_name_raises() -> None:
    with pytest.raises(UserInputError, match='no last name for "Priya"'):
        derive_email("Priya", domain=DOMAIN)


def test_TC_M2_10_other_domain() -> None:
    assert derive_email("Rahul Mehta", domain="example.org") == "rahul.mehta@example.org"


def test_normalize_name() -> None:
    assert normalize_name("  José   PÉREZ ") == "jose perez"
    assert normalize_name("Straße") == "strasse"
    assert normalize_name("") == ""


# --- Roster.resolve ---------------------------------------------------------------------------


def test_TC_M2_11_unique_first_name() -> None:
    r = roster("Priya Shah", "Rahul Mehta")
    res = r.resolve("Priya")
    assert_resolved(res, "priya.shah@coditas.com", "Priya Shah")
    assert res.owner_raw == "Priya"


def test_TC_M2_12_shared_first_name_is_ambiguous() -> None:
    res = roster("Priya Shah", "Priya Nair").resolve("Priya")
    assert res.owner_key is None
    assert res.owner_display is None
    assert res.owner_raw == "Priya"
    assert res.flags == {Flag.AMBIGUOUS_OWNER}
    assert res.candidates == ("priya.nair@coditas.com", "priya.shah@coditas.com")


def test_TC_M2_13_full_name_disambiguates() -> None:
    res = roster("Priya Shah", "Priya Nair").resolve("Priya Nair")
    assert_resolved(res, "priya.nair@coditas.com", "Priya Nair")


def test_TC_M2_14_first_name_and_last_initial() -> None:
    res = roster("Priya Shah", "Priya Nair").resolve("Priya S.")
    assert_resolved(res, "priya.shah@coditas.com", "Priya Shah")


def test_TC_M2_15_handle_matches_explicit_email_local_part() -> None:
    res = roster("Priya Shah <ps@client.com>", "Rahul Mehta").resolve("@ps")
    assert_resolved(res, "ps@client.com", "Priya Shah")
    assert res.owner_raw == "@ps"


def test_TC_M2_16_handle_matches_derived_local_part() -> None:
    res = roster("Priya Shah").resolve("@priya.shah")
    assert_resolved(res, "priya.shah@coditas.com", "Priya Shah")


def test_TC_M2_17_accents_ignored() -> None:
    res = roster("José Pérez").resolve("jose")
    assert_resolved(res, "jose.perez@coditas.com", "José Pérez")


def test_TC_M2_18_full_name_not_attendee_gets_derived_key() -> None:
    res = roster("Priya Shah").resolve("Vikram Rao")
    assert res.owner_key == "vikram.rao@coditas.com"
    assert res.owner_display == "Vikram Rao"
    assert res.owner_raw == "Vikram Rao"
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE}
    assert res.candidates == ()


def test_TC_M2_19_single_token_not_attendee() -> None:
    res = roster("Priya Shah").resolve("Vikram")
    assert res.owner_key is None
    assert res.owner_display is None
    assert res.owner_raw == "Vikram"
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED}


@pytest.mark.parametrize("owner", [None, "", "   "])
def test_TC_M2_20_no_owner_is_unassigned(owner: str | None) -> None:
    res = roster("Priya Shah").resolve(owner)
    assert res.owner_key is None
    assert res.owner_display is None
    assert res.flags == {Flag.UNASSIGNED}
    assert res.candidates == ()


def test_TC_M2_21_duplicates_merge_keeping_explicit_email() -> None:
    r = roster("Priya Shah", "Priya Shah <priya.shah@coditas.com>", "Rahul Mehta")
    assert [a.full_name for a in r.attendees] == ["Priya Shah", "Rahul Mehta"]
    assert r.attendees[0].email == "priya.shah@coditas.com"
    # The first entry already has the email: a later bare one does not replace it.
    r = roster("Priya Shah <priya.shah@coditas.com>", "priya shah")
    assert len(r.attendees) == 1
    assert r.attendees[0].email == "priya.shah@coditas.com"


def test_TC_M2_22_first_name_only_attendee_resolves_to_name_key() -> None:
    res = roster("Priya", "Rahul Mehta").resolve("Priya")
    assert_resolved(res, "name:priya", "Priya")


def test_TC_M2_23_last_initial_variants() -> None:
    r = roster("Priya Shah", "Priya Nair")
    assert_resolved(r.resolve("Priya N"), "priya.nair@coditas.com", "Priya Nair")
    assert_resolved(r.resolve("priya n."), "priya.nair@coditas.com", "Priya Nair")


# --- Edge cases (spec §6) and interpretations ---------------------------------------------------


def test_full_name_not_in_roster_beats_first_name_match() -> None:
    res = roster("Priya Shah").resolve("Priya Nair")
    assert res.owner_key == "priya.nair@coditas.com"
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE}


def test_identical_names_without_email_are_one_person() -> None:
    r = roster("Priya Shah", "Priya Shah")
    assert len(r.attendees) == 1
    assert_resolved(r.resolve("Priya"), "priya.shah@coditas.com", "Priya Shah")


def test_case_insensitive_full_name() -> None:
    assert_resolved(
        roster("Priya Shah").resolve("PRIYA SHAH"), "priya.shah@coditas.com", "Priya Shah"
    )


def test_email_owner_matches_attendee() -> None:
    r = roster("Priya Shah <ps@client.com>", "Rahul Mehta")
    assert_resolved(r.resolve("PS@client.com"), "ps@client.com", "Priya Shah")
    assert_resolved(r.resolve("rahul.mehta@coditas.com"), "rahul.mehta@coditas.com", "Rahul Mehta")


def test_email_owner_not_attendee() -> None:
    res = roster("Priya Shah").resolve("Vikram.Rao@coditas.com")
    assert res.owner_key == "vikram.rao@coditas.com"
    assert res.owner_display == "Vikram.Rao@coditas.com"
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE}


def test_handle_falls_back_to_name_rules() -> None:
    r = roster("Priya Shah", "Rahul Mehta")
    assert_resolved(r.resolve("@rahul"), "rahul.mehta@coditas.com", "Rahul Mehta")
    res = r.resolve("@vikram.rao")
    assert res.owner_key == "vikram.rao@coditas.com"
    assert res.owner_display == "@vikram.rao"
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE}


def test_handle_matching_two_attendees_is_ambiguous() -> None:
    res = roster("Priya Shah <ps@a.com>", "Pooja Singh <ps@b.com>").resolve("@ps")
    assert res.flags == {Flag.AMBIGUOUS_OWNER}
    assert res.candidates == ("ps@a.com", "ps@b.com")


def test_same_full_name_different_emails_is_ambiguous() -> None:
    res = roster("Priya Shah <ps@a.com>", "Priya Shah <ps@b.com>").resolve("Priya Shah")
    assert res.flags == {Flag.AMBIGUOUS_OWNER}
    assert res.candidates == ("ps@a.com", "ps@b.com")


def test_last_initial_matching_two_attendees_is_ambiguous() -> None:
    res = roster("Priya Shah", "Priya Sen", "Priya Nair").resolve("Priya S.")
    assert res.flags == {Flag.AMBIGUOUS_OWNER}
    assert res.candidates == ("priya.sen@coditas.com", "priya.shah@coditas.com")


def test_last_initial_matching_nobody_is_unassigned() -> None:
    # An initial is not a last name, so no email can be derived from it.
    res = roster("Priya Shah").resolve("Priya K.")
    assert res.owner_key is None
    assert res.owner_raw == "Priya K."
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED}


def test_first_name_only_attendee_wins_by_full_name_rule() -> None:
    # Rule 2 (full name) runs before rule 4b, and the full name of `Priya` is `Priya`.
    r = roster("Priya", "Priya Shah")
    assert_resolved(r.resolve("priya"), "name:priya", "Priya")
    assert_resolved(r.resolve("Priya S"), "priya.shah@coditas.com", "Priya Shah")


@pytest.mark.parametrize("owner", ["@.", "@_"])
def test_handle_without_letters_is_unassigned(owner: str) -> None:
    res = roster("Priya Shah").resolve(owner)
    assert res.owner_key is None
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED}


def test_multi_token_owner_with_no_derivable_email_is_unassigned() -> None:
    res = roster("Priya Shah").resolve("Vikram ???")
    assert res.owner_key is None
    assert res.flags == {Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED}


def test_owner_raw_kept_as_written() -> None:
    res = roster("Priya Shah").resolve("  priya ")
    assert res.owner_raw == "  priya "
    assert res.owner_key == "priya.shah@coditas.com"


def test_roster_constructor_and_domain() -> None:
    attendees = [attendee("Priya Shah", "example.org")]
    r = Roster(attendees, domain="example.org")
    assert r.attendees == tuple(attendees)
    assert r.resolve("Vikram Rao").owner_key == "vikram.rao@example.org"
    assert build_roster(["", "Priya"], domain=DOMAIN).attendees == (attendee("Priya"),)
