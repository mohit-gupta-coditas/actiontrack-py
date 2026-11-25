"""Subprocess harness for the M12 e2e tests: the CLI runs as `python -m actiontrack` (M12 §2)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NOTES = REPO / "notes"
EXPECTED = Path(__file__).with_name("expected.yaml")
FAKE_SERVER = Path(__file__).with_name("fake_gmail_server.py")
TODAY = "2026-11-25"

# Variables from the developer's shell that would change the CLI's behaviour.
_SCRUBBED = ("NO_COLOR", "FORCE_COLOR", "TTY_COMPATIBLE", "COLUMNS")


def needs_notes() -> None:
    if not NOTES.is_dir() or not EXPECTED.is_file():
        pytest.skip("sample notes/ not provided (G28)")


@dataclass
class Cli:
    """Runs the CLI on its own DB and config file, so the user's real ones are never touched."""

    db: Path
    config: Path
    cwd: Path = REPO

    def env(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("ACTIONTRACK_") and k not in _SCRUBBED
        }
        env.update(ACTIONTRACK_DB=str(self.db), ACTIONTRACK_TODAY=TODAY, PYTHONUTF8="1")
        env.update(extra or {})
        return env

    def __call__(
        self, *args: str, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "actiontrack", "--config", str(self.config), *args],
            cwd=self.cwd,
            env=self.env(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

    def json(self, *args: str) -> Any:
        r = self(*args, "--json")
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def items(self, *args: str) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = self.json("list", *args)["items"]
        return data


def make_cli(root: Path, config_text: str = "") -> Cli:
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.toml"
    outbox = (root / "outbox").as_posix()
    config.write_text(f'outbox_dir = "{outbox}"\n{config_text}', encoding="utf-8")
    return Cli(db=root / "actiontrack.db", config=config)


@pytest.fixture
def cli(tmp_path: Path) -> Cli:
    """A CLI with an empty DB."""
    return make_cli(tmp_path / "cli")


@pytest.fixture(scope="session")
def expected() -> dict[str, Any]:
    needs_notes()
    data: dict[str, Any] = yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="session")
def sample_ingest(tmp_path_factory: pytest.TempPathFactory) -> tuple[Cli, Any]:
    """`ingest notes` once per session: the CLI it ran on, and its completed process."""
    needs_notes()
    cli = make_cli(tmp_path_factory.mktemp("sample"))
    return cli, cli("ingest", "notes", "--report-json", str(cli.db.with_suffix(".report.json")))


@pytest.fixture
def ingested(sample_ingest: tuple[Cli, Any], tmp_path: Path) -> Cli:
    """A CLI on a private copy of the ingested sample DB, so tests may change it."""
    source, result = sample_ingest
    assert result.returncode == 0, result.stderr
    cli = make_cli(tmp_path / "cli")
    for suffix in ("", "-wal", "-shm"):
        src = Path(f"{source.db}{suffix}")
        if src.exists():
            shutil.copy(src, f"{cli.db}{suffix}")
    return cli


def same_file(reported: str, relative: str) -> bool:
    return Path(reported).resolve() == (REPO / relative).resolve()
