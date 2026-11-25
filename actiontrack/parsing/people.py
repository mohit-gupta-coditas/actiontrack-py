"""Attendee parsing, per-note rosters and owner resolution (M2 spec).

Every person gets a key: their explicit email (lowercased), else the email derived from their
full name, else `name:<first name>` for a first-name-only attendee (gap G1).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from actiontrack.errors import UserInputError
from actiontrack.models import Attendee, Flag, OwnerResolution

_EMAIL = r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+"
_EMAIL_FULL = re.compile(rf"^{_EMAIL}$")
# The email plus the brackets around it, if any: `<a@b.c>` or `(a@b.c)`.
_EMAIL_IN_TEXT = re.compile(rf"[<(]?\s*({_EMAIL})\s*[>)]?")
_TRAILING_ROLE = re.compile(r"\s*\([^()]*\)\s*$")
_LOCAL_PART_SEPARATORS = re.compile(r"[._]+")
_APOSTROPHES = re.compile("['\u2019\u2018`]")
_EMAIL_PART_SEPARATORS = re.compile(r"[\s\-\u2010-\u2015]+")
_NOT_EMAIL_CHAR = re.compile(r"[^a-z0-9]")
# `First L` or `First L.`: a first name and a last-name initial.
_FIRST_AND_INITIAL = re.compile(r"^(\S+)\s+(\w)\.?$")
_EDGE_PUNCTUATION = " \t_,;:"


def normalize_name(s: str) -> str:
    """Casefold, strip accents and collapse whitespace, for comparing names."""
    return " ".join(_strip_accents(s).casefold().split())


def derive_email(full_name: str, *, domain: str) -> str:
    """`Anna-Maria López` → `anna.maria.lopez@<domain>`. Raises if there is no last name."""
    text = _APOSTROPHES.sub("", _strip_accents(full_name).lower())
    parts = [_NOT_EMAIL_CHAR.sub("", p) for p in _EMAIL_PART_SEPARATORS.split(text)]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        raise UserInputError(f'cannot derive email: no last name for "{full_name.strip()}"')
    return f"{'.'.join(parts)}@{domain}"


def parse_attendee(raw: str, *, domain: str) -> Attendee | None:
    """Parse one raw attendee string. Returns None when it holds no name and no email."""
    text = raw.replace("*", "").strip()
    email: str | None = None
    m = _EMAIL_IN_TEXT.search(text)
    if m:
        email = m.group(1).lower()
        text = text[: m.start()] + text[m.end() :]
    while (role := _TRAILING_ROLE.search(text)) is not None:
        text = text[: role.start()]
    name = " ".join(text.strip(_EDGE_PUNCTUATION).split())
    if name.startswith("@"):
        name = _name_from_local_part(name[1:])
    if not _has_alnum(name):
        if email is None:
            return None
        name = _name_from_local_part(email.partition("@")[0])
    first, _, last = name.partition(" ")
    derived = _try_derive_email(name, domain=domain) if last else None
    return Attendee(
        full_name=name,
        first_name=first,
        last_name=last or None,
        email=email,
        key=email or derived or f"name:{normalize_name(first)}",
        derived_email=derived,
    )


class Roster:
    """The attendees of one note, deduplicated by key, used to resolve action-item owners."""

    def __init__(self, attendees: Sequence[Attendee], *, domain: str) -> None:
        by_key: dict[str, Attendee] = {}
        for a in attendees:
            kept = by_key.get(a.key)
            if kept is None or (kept.email is None and a.email is not None):
                by_key[a.key] = a
        self.attendees: tuple[Attendee, ...] = tuple(by_key.values())
        self._domain = domain

    def resolve(self, owner_raw: str | None) -> OwnerResolution:
        """Map the owner text of an action item to a person key (spec §5, rules 0-6)."""
        text = (owner_raw or "").strip().strip("*").strip()
        if not text:
            return self._result(owner_raw, flags={Flag.UNASSIGNED})

        # Rule 1: an email, or an @handle equal to an email's local part.
        if _EMAIL_FULL.match(text):
            wanted = text.lower()
            matches = [a for a in self.attendees if wanted in (a.email, a.derived_email)]
            if not matches:
                return self._result(
                    owner_raw, key=wanted, display=text, flags={Flag.OWNER_NOT_ATTENDEE}
                )
            return self._pick(owner_raw, matches)
        if text.startswith("@"):
            handle = text[1:].lower()
            matches = [a for a in self.attendees if handle in _local_parts(a)]
            if matches:
                return self._pick(owner_raw, matches)
            text = _name_from_local_part(text[1:])

        wanted = normalize_name(text)
        tokens = wanted.split()
        if not tokens:
            return self._result(owner_raw, flags={Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED})

        # Rule 2: full name.
        matches = [a for a in self.attendees if normalize_name(a.full_name) == wanted]
        if matches:
            return self._pick(owner_raw, matches)

        # Rule 3: `First L` / `First L.`.
        if m := _FIRST_AND_INITIAL.match(wanted):
            first, initial = m.groups()
            matches = [
                a
                for a in self.attendees
                if normalize_name(a.first_name) == first
                and a.last_name is not None
                and normalize_name(a.last_name).startswith(initial)
            ]
            if matches:
                return self._pick(owner_raw, matches)
            # An initial is not a last name: nothing to derive an email from.
            return self._result(owner_raw, flags={Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED})

        # Rules 4 / 4b: a first name.
        if len(tokens) == 1:
            matches = [a for a in self.attendees if normalize_name(a.first_name) == wanted]
            if matches:
                return self._pick(owner_raw, matches)
            # Rule 6.
            return self._result(owner_raw, flags={Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED})

        # Rule 5: a full name that is not in the roster.
        derived = _try_derive_email(text, domain=self._domain)
        if derived is None:
            return self._result(owner_raw, flags={Flag.OWNER_NOT_ATTENDEE, Flag.UNASSIGNED})
        return self._result(
            owner_raw,
            key=derived,
            display=(owner_raw or "").strip(),
            flags={Flag.OWNER_NOT_ATTENDEE},
        )

    def _pick(self, owner_raw: str | None, matches: Sequence[Attendee]) -> OwnerResolution:
        keys = sorted({a.key for a in matches})
        if len(keys) == 1:
            return self._result(owner_raw, key=keys[0], display=matches[0].full_name)
        return self._result(owner_raw, flags={Flag.AMBIGUOUS_OWNER}, candidates=tuple(keys))

    @staticmethod
    def _result(
        owner_raw: str | None,
        *,
        key: str | None = None,
        display: str | None = None,
        flags: Iterable[Flag] = (),
        candidates: tuple[str, ...] = (),
    ) -> OwnerResolution:
        return OwnerResolution(
            owner_key=key,
            owner_display=display,
            owner_raw=owner_raw,
            flags=frozenset(flags),
            candidates=candidates,
        )


def build_roster(attendees_raw: Iterable[str], *, domain: str) -> Roster:
    """Parse a note's raw attendee strings, dropping the unusable ones."""
    parsed = (parse_attendee(raw, domain=domain) for raw in attendees_raw)
    return Roster([a for a in parsed if a is not None], domain=domain)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _has_alnum(s: str) -> bool:
    return any(c.isalnum() for c in s)


def _name_from_local_part(local: str) -> str:
    """`priya.shah` / `priya_shah` → `Priya Shah`."""
    return " ".join(p.title() for p in _LOCAL_PART_SEPARATORS.split(local) if p)


def _local_parts(a: Attendee) -> set[str]:
    return {e.partition("@")[0] for e in (a.email, a.derived_email) if e}


def _try_derive_email(full_name: str, *, domain: str) -> str | None:
    try:
        return derive_email(full_name, domain=domain)
    except UserInputError:
        return None
