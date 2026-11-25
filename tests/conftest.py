from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import platformdirs
import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Keep tests away from the real config/data dirs and from ACTIONTRACK_* / colour env vars."""
    import os

    for name in list(os.environ):
        if name.startswith("ACTIONTRACK_") or name in ("NO_COLOR", "FORCE_COLOR", "TTY_COMPATIBLE"):
            monkeypatch.delenv(name, raising=False)
    home = tmp_path / "platformdirs"
    monkeypatch.setattr(
        platformdirs, "user_config_dir", lambda *a, **k: str(home / "config" / "actiontrack")
    )
    monkeypatch.setattr(
        platformdirs, "user_data_dir", lambda *a, **k: str(home / "data" / "actiontrack")
    )
    yield home
