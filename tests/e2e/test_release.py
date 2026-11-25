"""M12 release checks: clean-venv wheel install (TC-M12-14) and traceability (TC-M12-15)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from actiontrack import __version__
from tests.e2e.conftest import REPO

pytestmark = pytest.mark.slow

TRACE_CHECK = REPO / "scripts" / "trace_check.py"


def load_trace_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_check", TRACE_CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bin_dir(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def test_TC_M12_14_wheel_installs_into_a_clean_venv(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    dist, venv = tmp_path / "dist", tmp_path / "venv"
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=REPO, check=True)
    (wheel,) = dist.glob("actiontrack-*.whl")
    subprocess.run([uv, "venv", "--seed", str(venv)], check=True)
    python = bin_dir(venv) / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run([uv, "pip", "install", "--python", str(python), str(wheel)], check=True)
    r = subprocess.run(
        [str(bin_dir(venv) / "actiontrack"), "--version"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"actiontrack {__version__}\n"


def test_TC_M12_15_trace_check_passes() -> None:
    r = subprocess.run(
        [sys.executable, str(TRACE_CHECK)], capture_output=True, text=True, encoding="utf-8"
    )
    assert r.returncode == 0, r.stderr


def fake_repo(root: Path, *, owners: str, tests: str) -> Path:
    (root / "spec/modules/MA").mkdir(parents=True)
    (root / "spec/requirements.md").write_text(
        "## 18. Requirement Index\n| REQ-X-01 | a |\n| REQ-ACC-01..02 | b |\n## 19. Future\n",
        encoding="utf-8",
    )
    (root / "spec/plan.md").write_text(
        f"## 2. Modules\n| ID | Owned |\n|---|---|\n{owners}\n## 3. Next\n", encoding="utf-8"
    )
    (root / "spec/modules/MA/tests.md").write_text(tests, encoding="utf-8")
    return root


def test_trace_check_expands_ranges(tmp_path: Path) -> None:
    root = fake_repo(
        tmp_path,
        owners="| [M1](x) | X-01 |\n| [M2](y) | ACC-01..02 |",
        tests="REQ-X-01 REQ-ACC-01, REQ-ACC-02",
    )
    assert load_trace_check().check(root) == []


def test_trace_check_reports_untested_and_double_owned(tmp_path: Path) -> None:
    root = fake_repo(
        tmp_path,
        owners="| [M1](x) | X-01, ACC-01..02 |\n| [M2](y) | ACC-02, Y-09 |",
        tests="REQ-X-01 REQ-ACC-01",
    )
    assert load_trace_check().check(root) == [
        "REQ-ACC-02: no test case in spec/modules/*/tests.md",
        "REQ-ACC-02: owned by 2 modules ['M1', 'M2'] in plan §2",
        "REQ-Y-09: owned in plan §2 but not in root §18",
    ]
