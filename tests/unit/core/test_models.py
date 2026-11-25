from __future__ import annotations

import dataclasses
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from actiontrack import models
from actiontrack.models import (
    Attendee,
    DueResolution,
    ExistingItem,
    Flag,
    IngestReport,
    ItemGroup,
    LineWarning,
    MergeDecision,
    NoteMeta,
    OwnerResolution,
    ParsedItem,
    Person,
    SkipReason,
    SkipRecord,
    WarningCode,
)

NOTE = Path("notes/2026-11-02-sync.md")
OWNER = OwnerResolution(
    owner_key="priya.shah@coditas.com",
    owner_display="Priya Shah",
    owner_raw="Priya",
    flags=frozenset(),
    candidates=(),
)
DUE = DueResolution(
    due_date=date(2026, 11, 6), due_raw="by Friday", flags=frozenset(), span=(20, 29)
)
PARSED = ParsedItem(
    note_path=NOTE,
    line_no=12,
    raw_text="- [ ] Priya to update docs by Friday",
    meeting_date=date(2026, 11, 2),
    note_title="Sync",
    owner=OWNER,
    task="update docs",
    due=DUE,
    checked=False,
    flags=frozenset({Flag.NO_DUE, Flag.MULTI_OWNER}),
)
DECISION = MergeDecision(
    item_id="a3f91c", kind="fuzzy", score=91.5, source=(NOTE, 12), matched_task_norm="update doc"
)

SAMPLES: list[Any] = [
    NoteMeta(
        path=NOTE,
        sha256="ab" * 32,
        meeting_date=date(2026, 11, 2),
        title="Sync",
        attendees_raw=("Priya Shah",),
        lines=((5, "text"),),
    ),
    SkipRecord(path=NOTE, reason=SkipReason.MISSING_DATE, detail="missing meeting date"),
    LineWarning(path=NOTE, line_no=41, code=WarningCode.MALFORMED_CHECKBOX, text="-[ ] x"),
    Attendee(
        full_name="Priya Shah",
        first_name="Priya",
        last_name="Shah",
        email=None,
        key="priya.shah@coditas.com",
        derived_email="priya.shah@coditas.com",
    ),
    OWNER,
    DUE,
    PARSED,
    ExistingItem(
        id="a3f91c",
        owner_key=None,
        task_norms=frozenset({"update doc"}),
        status="open",
        done_source=None,
        done_at=None,
    ),
    DECISION,
    ItemGroup(
        id="a3f91c",
        owner_key="priya.shah@coditas.com",
        owner_display="Priya Shah",
        owner_raw="Priya",
        task="update docs",
        task_norm="update doc",
        due_date=None,
        due_raw=None,
        status="done",
        done_source="cli",
        done_at=datetime(2026, 11, 20, 9, 0, tzinfo=UTC),
        flags=frozenset(),
        first_seen=date(2026, 11, 2),
        last_seen=date(2026, 11, 9),
        sources=(PARSED,),
    ),
    Person(key="name:priya", full_name="Priya", first_name="Priya", email=None),
]


def make_report() -> IngestReport:
    return IngestReport(
        scanned=3,
        ingested=1,
        unchanged=1,
        removed=0,
        skipped=(
            SkipRecord(path=NOTE, reason=SkipReason.INVALID_FRONTMATTER, detail="x", line_no=4),
        ),
        warnings=(LineWarning(path=NOTE, line_no=41, code=WarningCode.EMPTY_TASK, text="- [ ]"),),
        sources_total=2,
        items_total=1,
        exact_merges=0,
        fuzzy_merges=1,
        flag_counts={Flag.UNASSIGNED: 5, Flag.NO_DUE: 4},
        decisions=(DECISION,),
    )


def test_samples_cover_every_contract() -> None:
    contracts = {
        obj
        for obj in vars(models).values()
        if isinstance(obj, type)
        and dataclasses.is_dataclass(obj)
        and obj.__module__ == models.__name__
    }
    assert {type(s) for s in SAMPLES} | {IngestReport} == contracts


@pytest.mark.parametrize("sample", [*SAMPLES, make_report()], ids=lambda s: type(s).__name__)
def test_TC_M0_25_contracts_are_frozen(sample: Any) -> None:
    first = dataclasses.fields(sample)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(sample, first, None)
    assert not hasattr(sample, "__dict__")  # slots=True


def test_TC_M0_26_ingest_report_to_json() -> None:
    data = make_report().to_json()
    text = json.dumps(data)
    assert json.loads(text) == data
    assert data["schema_version"] == 1
    assert data["skipped"][0] == {
        "path": "notes/2026-11-02-sync.md",
        "reason": "invalid_frontmatter",
        "detail": "x",
        "line_no": 4,
    }
    assert data["warnings"][0]["code"] == "empty_task"
    assert data["flag_counts"] == {"unassigned": 5, "no_due": 4}
    assert data["decisions"][0]["source"] == ["notes/2026-11-02-sync.md", 12]


def test_to_jsonable_dates_and_sets() -> None:
    group = SAMPLES[-2]
    data = models.to_jsonable(group)
    assert data["done_at"] == "2026-11-20T09:00:00+00:00"
    assert data["first_seen"] == "2026-11-02"
    assert data["sources"][0]["flags"] == ["multi_owner", "no_due"]
    assert data["sources"][0]["due"]["span"] == [20, 29]
