"""Dedup & item IDs: parsed sources → unique action items with stable IDs (M5 spec).

`group_items` is pure: the same sources and existing items always give the same groups, whatever
order they are passed in.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from actiontrack.errors import UserInputError
from actiontrack.models import (
    ExistingItem,
    Flag,
    ItemGroup,
    MergeDecision,
    OwnerResolution,
    ParsedItem,
)

Scorer = Callable[[str, str], float]

_NON_WORD = re.compile(r"[^\w\s]")
_STOP_WORDS = frozenset({"the", "a", "an"})
_HEX = re.compile(r"^[0-9a-f]+$")
_OWNER_FLAGS = frozenset(
    {Flag.UNASSIGNED, Flag.AMBIGUOUS_OWNER, Flag.OWNER_NOT_ATTENDEE, Flag.MULTI_OWNER}
)
_MIN_PREFIX = 4


@dataclass(frozen=True)
class DedupConfig:
    fuzzy_enabled: bool = True
    threshold: int = 88
    scorer: Scorer | None = None  # default rapidfuzz.fuzz.token_set_ratio; injectable for tests


@dataclass(frozen=True)
class DedupResult:
    groups: tuple[ItemGroup, ...]
    decisions: tuple[MergeDecision, ...]
    orphaned_ids: tuple[str, ...]  # existing ids that matched no source


@dataclass
class _Group:
    identity: str | None  # owner key, or `?<candidates>` for an ambiguous owner (§4)
    canonical_norm: str
    norms: set[str]
    existing: ExistingItem | None = None
    members: list[ParsedItem] = field(default_factory=list)

    @property
    def id(self) -> str:
        if self.existing is not None:
            return self.existing.id
        return make_item_id(self.identity, self.canonical_norm)


def normalize_task(task: str) -> str:
    """NFKC + casefold, punctuation → space, drop `the`/`a`/`an`, collapse whitespace."""
    s = _NON_WORD.sub(" ", unicodedata.normalize("NFKC", task).casefold())
    return " ".join(w for w in s.split() if w not in _STOP_WORDS)


def make_item_id(owner_key: str | None, task_norm: str) -> str:
    """40-hex sha1 of `<owner_key or ∅>|<task_norm>`."""
    return hashlib.sha1(f"{owner_key or '∅'}|{task_norm}".encode()).hexdigest()


def group_items(
    sources: Sequence[ParsedItem], existing: Sequence[ExistingItem], cfg: DedupConfig
) -> DedupResult:
    """Group every source into unique items, merge their fields and log each join."""
    scorer = _scorer(cfg)
    groups = [
        _Group(e.owner_key, min(e.task_norms), set(e.task_norms), existing=e)
        for e in sorted(existing, key=lambda e: e.id)
        if e.task_norms
    ]
    shells = {g.id: g for g in groups}
    # Shells with no norms can never match a source, so they are orphaned straight away.
    orphaned = [e.id for e in existing if not e.task_norms]
    decisions: list[MergeDecision] = []

    for s in sorted(sources, key=lambda s: (s.meeting_date, str(s.note_path), s.line_no)):
        n = normalize_task(s.task)
        identity = _identity(s.owner)
        kind: Literal["exact", "fuzzy"] = "exact"
        score = 100.0
        matched = n
        same_owner = [g for g in groups if g.identity == identity]

        target = next((g for g in same_owner if n in g.norms), None)
        if target is None and scorer is not None and s.owner.owner_key is not None:
            best: _Group | None = None
            best_score = -1.0
            for g in same_owner:  # strict `>` keeps the earliest-created group on a tie
                sc = float(scorer(n, g.canonical_norm))
                if sc > best_score:
                    best, best_score = g, sc
            if best is not None and best_score >= cfg.threshold:
                target, kind, score, matched = best, "fuzzy", best_score, best.canonical_norm
        if target is None:
            # A shell that already carries this item's ID (e.g. an ambiguous owner, whose
            # candidates are not stored) is the same item.
            target = shells.get(make_item_id(identity, n))

        if target is None:
            groups.append(_Group(identity, n, {n}, members=[s]))
            continue
        if target.members:
            decisions.append(
                MergeDecision(
                    item_id=target.id,
                    kind=kind,
                    score=score,
                    source=(s.note_path, s.line_no),
                    matched_task_norm=matched,
                )
            )
        target.members.append(s)
        target.norms.add(n)

    orphaned += [g.id for g in groups if not g.members]
    return DedupResult(
        groups=tuple(_merge(g) for g in groups if g.members),
        decisions=tuple(decisions),
        orphaned_ids=tuple(sorted(orphaned)),
    )


def shortest_unique_prefixes(ids: Iterable[str], *, min_len: int = 6) -> dict[str, str]:
    """Each ID's shortest prefix (at least `min_len` chars) that no other ID in the set shares."""
    ordered = sorted(set(ids))
    out: dict[str, str] = {}
    for i, item_id in enumerate(ordered):
        neighbours = ordered[max(i - 1, 0) : i] + ordered[i + 1 : i + 2]
        shared = max((_common_prefix_len(item_id, o) for o in neighbours), default=0)
        out[item_id] = item_id[: max(min_len, shared + 1)]
    return out


def resolve_prefix(prefix: str, ids: Iterable[str]) -> str:
    """The one ID starting with `prefix` (case-insensitive, at least 4 hex chars)."""
    p = prefix.strip().lower()
    if len(p) < _MIN_PREFIX or not _HEX.match(p):
        raise UserInputError(
            f'invalid id "{prefix.strip()}"',
            hint=f"use at least {_MIN_PREFIX} hex characters of an item id",
        )
    all_ids = set(ids)
    matches = sorted(i for i in all_ids if i.startswith(p))
    if not matches:
        raise UserInputError(f'no item with id "{p}"')
    if len(matches) > 1:
        short = shortest_unique_prefixes(all_ids)
        raise UserInputError(
            f'id "{p}" matches {len(matches)} items', hint=", ".join(short[m] for m in matches)
        )
    return matches[0]


def _scorer(cfg: DedupConfig) -> Scorer | None:
    if not cfg.fuzzy_enabled:
        return None
    if cfg.scorer is not None:
        return cfg.scorer
    from rapidfuzz import fuzz  # imported lazily: only needed when fuzzy matching runs

    return fuzz.token_set_ratio


def _identity(owner: OwnerResolution) -> str | None:
    """Who an item belongs to for grouping. Ambiguous owners group by their candidate set."""
    if owner.owner_key is not None:
        return owner.owner_key
    if owner.candidates:
        return "?" + ",".join(sorted(owner.candidates))
    return None


def _merge(g: _Group) -> ItemGroup:
    first, latest = g.members[0], g.members[-1]
    dated = [m for m in g.members if m.due.due_date is not None]
    # Latest meeting with a resolved due wins (ties → later line); else keep an unparsed phrase.
    candidates = dated or [m for m in g.members if m.due.due_raw is not None] or [latest]
    due_from = max(candidates, key=lambda m: (m.meeting_date, m.line_no))
    due_date = due_from.due.due_date

    flags: frozenset[Flag] = frozenset().union(*(m.flags & _OWNER_FLAGS for m in g.members))
    if all(m.due.due_raw is None for m in g.members):
        flags |= {Flag.NO_DUE}
    if due_date is None and any(Flag.UNPARSED_DUE in m.due.flags for m in g.members):
        flags |= {Flag.UNPARSED_DUE}

    e = g.existing
    status: Literal["open", "done"]
    done_source: Literal["note", "cli"] | None
    done_at: datetime | None
    if e is not None and e.status == "done":
        status, done_source, done_at = "done", e.done_source, e.done_at
    elif any(m.checked for m in g.members):
        status, done_source, done_at = "done", "note", None
    else:
        status, done_source, done_at = "open", None, None

    return ItemGroup(
        id=g.id,
        owner_key=first.owner.owner_key,
        owner_display=latest.owner.owner_display,
        owner_raw=latest.owner.owner_raw,
        task=first.task,
        task_norm=normalize_task(first.task),
        due_date=due_date,
        due_raw=due_from.due.due_raw,
        status=status,
        done_source=done_source,
        done_at=done_at,
        flags=flags,
        first_seen=min(m.meeting_date for m in g.members),
        last_seen=max(m.meeting_date for m in g.members),
        sources=tuple(g.members),
    )


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n
