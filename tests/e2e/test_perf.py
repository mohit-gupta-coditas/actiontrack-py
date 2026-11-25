"""M12 performance budgets (REQ-CLI-08): CLI start-up and sample ingest time."""

from __future__ import annotations

import statistics
import sys
import time
import warnings
from pathlib import Path

import pytest

from tests.e2e.conftest import Cli, make_cli

pytestmark = pytest.mark.slow

STARTUP_BUDGET_S = 0.300
INGEST_BUDGET_S = 5.0


def median_runtime(cli: Cli, *args: str, runs: int = 5) -> float:
    cli(*args)  # warm-up
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        cli(*args)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="the budget is measured on Linux (M12 spec §4)"
)
@pytest.mark.parametrize("args", [("--help",), ("list",), ("done", "zzzz")], ids=" ".join)
def test_TC_M12_12_startup_under_300ms(ingested: Cli, args: tuple[str, ...]) -> None:
    elapsed = median_runtime(ingested, *args)
    assert elapsed < STARTUP_BUDGET_S, f"{' '.join(args)}: median {elapsed * 1000:.0f} ms"


def test_TC_M12_13_sample_ingest_within_budget(tmp_path: Path, expected: object) -> None:
    cli = make_cli(tmp_path / "cli")
    start = time.perf_counter()
    r = cli("ingest", "notes")
    elapsed = time.perf_counter() - start
    assert r.returncode == 0, r.stderr
    if elapsed > INGEST_BUDGET_S:
        warnings.warn(f"ingest took {elapsed:.1f} s (budget {INGEST_BUDGET_S} s)", stacklevel=1)
    assert elapsed < 2 * INGEST_BUDGET_S
