from __future__ import annotations

import dataclasses
import hashlib
import random
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from actiontrack.dedup import (
    DedupConfig,
    DedupResult,
    group_items,
    make_item_id,
    normalize_task,
    resolve_prefix,
    shortest_unique_prefixes,
)
from actiontrack.errors import UserInputError
from actiontrack.models import ExistingItem, Flag, ParsedItem
from tests.unit.conftest import owner, src

PRIYA = "priya.shah@coditas.com"
RAHUL = "rahul.mehta@coditas.com"
DEFAULT = DedupConfig()


def group(
    *sources: ParsedItem, cfg: DedupConfig = DEFAULT, existing: tuple[ExistingItem, ...] = ()
) -> DedupResult:
    return group_items(list(sources), list(existing), cfg)


def stub(scores: dict[frozenset[str], float]) -> DedupConfig:
    """A config whose scorer looks pairs up in `scores` (order-insensitive), 0 otherwise."""
    return DedupConfig(scorer=lambda a, b: scores.get(frozenset({a, b}), 0.0))


def existing_item(
    item_id: str,
    key: str | None,
    *norms: str,
    status: str = "open",
    done_source: str | None = None,
    done_at: datetime | None = None,
) -> ExistingItem:
    return ExistingItem(item_id, key, frozenset(norms), status, done_source, done_at)  # type: ignore[arg-type]


# --- normalization ---------------------------------------------------------------------------


def test_TC_M5_01_normalize_task() -> None:
    assert normalize_task("Send the revised Quote!") == "send revised quote"


def test_TC_M5_02_digits_are_kept() -> None:
    assert normalize_task("Ship v2") != normalize_task("Ship v3")


def test_normalize_task_nfkc_and_stop_words_only_as_words() -> None:
    fullwidth_a, em_dash = chr(0xFF21), chr(0x2014)
    raw = f"  {fullwidth_a}n  ANALYSIS{em_dash}of   the theme  "
    assert normalize_task(raw) == "analysis of theme"


# --- grouping --------------------------------------------------------------------------------


def test_TC_M5_03_exact_merge_across_notes() -> None:
    r = group(
        src(PRIYA, "Send revised quote.", "2026-11-04", path="a.md"),
        src(PRIYA, "send the revised quote", "2026-11-18", path="b.md"),
    )
    assert len(r.groups) == 1
    assert len(r.groups[0].sources) == 2
    assert [(d.kind, d.score) for d in r.decisions] == [("exact", 100.0)]


def test_TC_M5_04_different_owners_never_merge() -> None:
    r = group(src(PRIYA, "send quote", "2026-11-04"), src(RAHUL, "send quote", "2026-11-04", 2))
    assert len(r.groups) == 2
    assert r.decisions == ()


def test_TC_M5_05_fuzzy_merge() -> None:
    r = group(
        src(PRIYA, "send revised quote", "2026-11-04"),
        src(PRIYA, "send revised quote to client", "2026-11-18"),
    )
    assert len(r.groups) == 1
    (d,) = r.decisions
    assert d.kind == "fuzzy"
    assert d.score >= 88


def test_TC_M5_06_different_object_not_merged() -> None:
    r = group(
        src(PRIYA, "send revised quote", "2026-11-04"),
        src(PRIYA, "send revised invoice", "2026-11-18"),
    )
    assert len(r.groups) == 2


def test_TC_M5_07_no_false_merge_at_default_threshold() -> None:
    r = group(src(PRIYA, "update doc", "2026-11-04"), src(PRIYA, "update docs page", "2026-11-18"))
    assert len(r.groups) == 2


def test_TC_M5_08_score_below_threshold_not_merged() -> None:
    cfg = DedupConfig(threshold=88, scorer=lambda a, b: 87.0)
    r = group(src(PRIYA, "alpha", "2026-11-04"), src(PRIYA, "beta", "2026-11-18"), cfg=cfg)
    assert len(r.groups) == 2


def test_TC_M5_09_score_at_threshold_merged() -> None:
    cfg = DedupConfig(threshold=88, scorer=lambda a, b: 88.0)
    r = group(src(PRIYA, "alpha", "2026-11-04"), src(PRIYA, "beta", "2026-11-18"), cfg=cfg)
    assert len(r.groups) == 1
    assert [(d.kind, d.score, d.matched_task_norm) for d in r.decisions] == [
        ("fuzzy", 88.0, "alpha")
    ]


def test_TC_M5_10_fuzzy_disabled() -> None:
    r = group(
        src(PRIYA, "send revised quote", "2026-11-04"),
        src(PRIYA, "send revised quote to client", "2026-11-18"),
        cfg=DedupConfig(fuzzy_enabled=False),
    )
    assert len(r.groups) == 2


def test_TC_M5_11_no_owner_merges_only_exactly() -> None:
    near = group(
        src(None, "send revised quote", "2026-11-04"),
        src(None, "send revised quote to client", "2026-11-18"),
        cfg=DedupConfig(scorer=lambda a, b: 100.0),
    )
    assert len(near.groups) == 2
    same = group(
        src(None, "Send the revised quote", "2026-11-04"),
        src(None, "send revised quote!", "2026-11-18"),
    )
    assert len(same.groups) == 1
    assert same.groups[0].owner_key is None
    assert same.groups[0].id == make_item_id(None, "send revised quote")


def test_TC_M5_12_no_chain_merges() -> None:
    cfg = stub(
        {
            frozenset({"alpha", "beta"}): 90,
            frozenset({"beta", "gamma"}): 90,
            frozenset({"alpha", "gamma"}): 70,
        }
    )
    r = group(
        src(PRIYA, "Alpha", "2026-11-04", 1),
        src(PRIYA, "Beta", "2026-11-04", 2),
        src(PRIYA, "Gamma", "2026-11-04", 3),
        cfg=cfg,
    )
    assert [[s.task for s in g.sources] for g in r.groups] == [["Alpha", "Beta"], ["Gamma"]]


def test_fuzzy_tie_joins_earliest_group() -> None:
    cfg = stub({frozenset({"alpha", "gamma"}): 95, frozenset({"beta", "gamma"}): 95})
    r = group(
        src(PRIYA, "Alpha", "2026-11-04", 1),
        src(PRIYA, "Beta", "2026-11-04", 2),
        src(PRIYA, "Gamma", "2026-11-04", 3),
        cfg=cfg,
    )
    assert [[s.task for s in g.sources] for g in r.groups] == [["Alpha", "Gamma"], ["Beta"]]


def test_fuzzy_picks_best_scoring_group() -> None:
    cfg = stub({frozenset({"alpha", "gamma"}): 89, frozenset({"beta", "gamma"}): 95})
    r = group(
        src(PRIYA, "Alpha", "2026-11-04", 1),
        src(PRIYA, "Beta", "2026-11-04", 2),
        src(PRIYA, "Gamma", "2026-11-04", 3),
        cfg=cfg,
    )
    assert [[s.task for s in g.sources] for g in r.groups] == [["Alpha"], ["Beta", "Gamma"]]


def test_TC_M5_25_ambiguous_owner_needs_equal_candidates() -> None:
    ab = owner(None, candidates=(PRIYA, RAHUL))
    ac = owner(None, candidates=(PRIYA, "priya.rao@coditas.com"))
    r = group(src(ab, "send quote", "2026-11-04"), src(ac, "send quote", "2026-11-18"))
    assert len(r.groups) == 2
    assert len({g.id for g in r.groups}) == 2  # distinct ids even though both owners are None

    same = group(
        src(ab, "send quote", "2026-11-04"),
        src(owner(None, candidates=(RAHUL, PRIYA)), "send quote", "2026-11-18"),
    )
    assert len(same.groups) == 1


def test_rapidfuzz_is_imported_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "rapidfuzz", None)  # any import of it now fails
    r = group(
        src(PRIYA, "a", "2026-11-04"),
        src(PRIYA, "b", "2026-11-04", 2),
        cfg=DedupConfig(fuzzy_enabled=False),
    )
    assert len(r.groups) == 2


# --- merged fields ---------------------------------------------------------------------------


def test_TC_M5_13_latest_due_and_seen_dates() -> None:
    (g,) = group(
        src(PRIYA, "send quote", "2026-11-04", due="2026-11-07", path="a.md"),
        src(PRIYA, "send quote", "2026-11-18", due="2026-11-20", path="b.md"),
    ).groups
    assert g.due_date == date(2026, 11, 20)
    assert g.due_raw == "by 2026-11-20"
    assert g.first_seen == date(2026, 11, 4)
    assert g.last_seen == date(2026, 11, 18)
    assert Flag.NO_DUE not in g.flags


def test_TC_M5_14_latest_member_with_a_due_wins() -> None:
    (g,) = group(
        src(PRIYA, "send quote", "2026-11-04", due="2026-11-07", path="a.md"),
        src(PRIYA, "send quote", "2026-11-18", path="b.md"),
    ).groups
    assert g.due_date == date(2026, 11, 7)
    assert Flag.NO_DUE not in g.flags


def test_due_tie_on_meeting_date_takes_highest_line() -> None:
    (g,) = group(
        src(PRIYA, "send quote", "2026-11-04", 9, due="2026-11-09"),
        src(PRIYA, "send quote", "2026-11-04", 3, due="2026-11-30"),
    ).groups
    assert g.due_date == date(2026, 11, 9)


def test_due_flags() -> None:
    (none,) = group(src(PRIYA, "send quote", "2026-11-04")).groups
    assert Flag.NO_DUE in none.flags
    assert Flag.UNPARSED_DUE not in none.flags

    (unparsed,) = group(
        src(PRIYA, "send quote", "2026-11-04", due_raw="ASAP"),
        src(PRIYA, "send quote", "2026-11-18"),
    ).groups
    assert (unparsed.due_date, unparsed.due_raw) == (None, "ASAP")
    assert unparsed.flags & {Flag.NO_DUE, Flag.UNPARSED_DUE} == {Flag.UNPARSED_DUE}

    (resolved,) = group(
        src(PRIYA, "send quote", "2026-11-04", due_raw="ASAP"),
        src(PRIYA, "send quote", "2026-11-18", due="2026-11-20"),
    ).groups
    assert resolved.due_date == date(2026, 11, 20)
    assert resolved.flags & {Flag.NO_DUE, Flag.UNPARSED_DUE} == set()


def test_owner_flags_union_and_latest_owner_display() -> None:
    later = dataclasses.replace(
        owner(PRIYA),
        owner_display="Priya S",
        owner_raw="Priya S",
        flags=frozenset({Flag.OWNER_NOT_ATTENDEE}),
    )
    a = src(PRIYA, "send quote", "2026-11-04")
    multi = src(later, "send quote", "2026-11-18")
    multi = dataclasses.replace(multi, flags=multi.flags | {Flag.MULTI_OWNER})
    (g,) = group(a, multi).groups
    assert g.owner_display == "Priya S"
    assert g.owner_raw == "Priya S"
    assert g.flags == {Flag.OWNER_NOT_ATTENDEE, Flag.MULTI_OWNER, Flag.NO_DUE}
    assert g.task == "send quote"
    assert g.task_norm == "send quote"


def test_TC_M5_15_checked_in_any_note_is_done() -> None:
    (g,) = group(
        src(PRIYA, "send quote", "2026-11-04", checked=True, path="a.md"),
        src(PRIYA, "send quote", "2026-11-18", checked=False, path="b.md"),
    ).groups
    assert (g.status, g.done_source, g.done_at) == ("done", "note", None)


def test_open_when_nothing_checked() -> None:
    (g,) = group(src(PRIYA, "send quote", "2026-11-04")).groups
    assert (g.status, g.done_source, g.done_at) == ("open", None, None)


def test_TC_M5_16_cli_done_is_sticky_and_keeps_id() -> None:
    done_at = datetime(2026, 11, 19, 10, 0)
    shell = existing_item(
        "f" * 40, PRIYA, "send quote", status="done", done_source="cli", done_at=done_at
    )
    r = group(
        src(PRIYA, "send quote", "2026-11-04"),
        src(PRIYA, "Send the quote", "2026-11-18"),
        existing=(shell,),
    )
    (g,) = r.groups
    assert (g.id, g.status, g.done_source, g.done_at) == ("f" * 40, "done", "cli", done_at)
    assert r.orphaned_ids == ()


def test_shell_fuzzy_match_keeps_id_and_task_comes_from_first_member() -> None:
    shell = existing_item("e" * 40, PRIYA, "send revised quote")
    r = group(src(PRIYA, "send revised quote to client", "2026-11-04"), existing=(shell,))
    (g,) = r.groups
    assert g.id == "e" * 40
    assert g.task_norm == "send revised quote to client"
    assert r.decisions == ()  # the first member of a shell is not a merge


def test_shell_reached_by_id_for_ambiguous_owner() -> None:
    amb = owner(None, candidates=(PRIYA, RAHUL))
    first = group(src(amb, "send quote", "2026-11-04"))
    (g0,) = first.groups
    shell = existing_item(g0.id, None, "send quote", status="done", done_source="cli")
    (g,) = group(src(amb, "send quote", "2026-11-04"), existing=(shell,)).groups
    assert (g.id, g.status, g.done_source) == (g0.id, "done", "cli")


def test_TC_M5_17_unmatched_existing_item_is_orphaned() -> None:
    r = group(
        src(PRIYA, "send quote", "2026-11-04"),
        existing=(
            existing_item("a" * 40, PRIYA, "book venue"),
            existing_item("b" * 40, RAHUL, "send quote"),
            existing_item("c" * 40, PRIYA),  # no norms at all
        ),
    )
    assert r.orphaned_ids == ("a" * 40, "b" * 40, "c" * 40)
    assert [g.id for g in r.groups] == [make_item_id(PRIYA, "send quote")]


# --- determinism and decisions ---------------------------------------------------------------


def test_TC_M5_18_shuffled_input_gives_identical_groups() -> None:
    sources = [
        src(PRIYA, "send revised quote", "2026-11-04", 3, due="2026-11-07", path="a.md"),
        src(PRIYA, "Send the revised quote to client", "2026-11-18", 1, path="b.md"),
        src(RAHUL, "book venue", "2026-11-04", 5, checked=True, path="a.md"),
        src(None, "tidy backlog", "2026-11-11", 2, path="c.md"),
        src(RAHUL, "book the venue", "2026-11-11", 4, due="2026-11-14", path="c.md"),
        src(None, "tidy backlog", "2026-11-04", 9, path="a.md"),
    ]
    expected = group_items(sources, [], DEFAULT)
    rng = random.Random(5)
    for _ in range(5):
        shuffled = sources[:]
        rng.shuffle(shuffled)
        assert group_items(shuffled, [], DEFAULT) == expected


def test_TC_M5_24_one_decision_per_join() -> None:
    r = group(
        src(PRIYA, "send revised quote", "2026-11-04", 1, path="a.md"),
        src(PRIYA, "Send the revised quote", "2026-11-11", 2, path="b.md"),
        src(PRIYA, "send revised quote to client", "2026-11-18", 3, path="c.md"),
        src(RAHUL, "book venue", "2026-11-04", 4, path="a.md"),
        src(RAHUL, "book venue", "2026-11-18", 5, path="c.md"),
    )
    pid = make_item_id(PRIYA, "send revised quote")
    rid = make_item_id(RAHUL, "book venue")
    got = [(d.item_id, d.kind, d.score, d.source, d.matched_task_norm) for d in r.decisions]
    assert got == [
        (pid, "exact", 100.0, (Path("b.md"), 2), "send revised quote"),
        (pid, "fuzzy", 100.0, (Path("c.md"), 3), "send revised quote"),
        (rid, "exact", 100.0, (Path("c.md"), 5), "book venue"),
    ]


# --- ids -------------------------------------------------------------------------------------


def test_TC_M5_19_make_item_id() -> None:
    assert make_item_id("k", "n") == hashlib.sha1(b"k|n").hexdigest()
    assert make_item_id(None, "n") == hashlib.sha1("∅|n".encode()).hexdigest()
    assert len(make_item_id("k", "n")) == 40


def test_TC_M5_20_shortest_unique_prefixes() -> None:
    a, b = "abc123ff" + "0" * 32, "abc124ee" + "0" * 32
    assert shortest_unique_prefixes([a, b]) == {a: "abc123", b: "abc124"}
    c, d = "abc123ff" + "0" * 32, "abc123fe" + "0" * 32
    assert shortest_unique_prefixes([c, d]) == {c: "abc123ff", d: "abc123fe"}
    assert shortest_unique_prefixes([]) == {}
    assert shortest_unique_prefixes([a], min_len=4) == {a: "abc1"}


def test_TC_M5_21_ambiguous_prefix() -> None:
    ids = ["abc123ff" + "0" * 32, "abc124ee" + "0" * 32]
    with pytest.raises(UserInputError, match="matches 2 items") as exc:
        resolve_prefix("abc12", ids)
    assert exc.value.hint == "abc123, abc124"


@pytest.mark.parametrize("prefix", ["ab", "zzzz", "xyz!"])
def test_TC_M5_22_invalid_or_unknown_prefix(prefix: str) -> None:
    with pytest.raises(UserInputError):
        resolve_prefix(prefix, ["abc123ff" + "0" * 32])


def test_unknown_prefix_message() -> None:
    with pytest.raises(UserInputError, match='no item with id "dddd"'):
        resolve_prefix("dddd", ["abc123ff" + "0" * 32])


def test_TC_M5_23_prefix_is_case_insensitive() -> None:
    full = "abc123ff" + "0" * 32
    assert resolve_prefix(" ABC123 ", [full, "def456" + "0" * 34]) == full
