"""Traceability check (M12 §5, TC-M12-15).

Fails if a REQ ID in root spec §18 has no test case in spec/modules/*/tests.md, is owned by no
module or by more than one in the plan §2 table, or is owned there without being in §18.
Ranges such as `CLI-01..07` and `REQ-ACC-01..11` are expanded (G30).

    python scripts/trace_check.py [repo-root]
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ID = re.compile(r"(?:REQ-)?([A-Z]+)-(\d+)(?:\.\.(\d+))?")


def expand(text: str, *, prefixed: bool = True) -> list[str]:
    """Every REQ ID in `text`, with `X-01..03` ranges expanded to `REQ-X-01`, `REQ-X-02`, ..."""
    pattern = r"REQ-" + ID.pattern.removeprefix("(?:REQ-)?") if prefixed else ID.pattern
    out: list[str] = []
    for m in re.finditer(pattern, text):
        area, first, last = m[1], m[2], m[3]
        width = len(first)
        for n in range(int(first), int(last or first) + 1):
            out.append(f"REQ-{area}-{n:0{width}d}")
    return out


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end >= 0 else None]


def required_ids(root: Path) -> set[str]:
    index = section((root / "spec/requirements.md").read_text(encoding="utf-8"), "## 18.")
    return set(expand(index))


def owners(root: Path) -> dict[str, list[str]]:
    table = section((root / "spec/plan.md").read_text(encoding="utf-8"), "## 2.")
    owned: dict[str, list[str]] = defaultdict(list)
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"\[(M\d+)\]", cells[0]) if cells else None
        if m:
            for req in expand(cells[-1], prefixed=False):
                owned[req].append(m[1])
    return owned


def tested_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for tests in sorted((root / "spec/modules").glob("*/tests.md")):
        ids.update(expand(tests.read_text(encoding="utf-8")))
    return ids


def check(root: Path) -> list[str]:
    required, owned, tested = required_ids(root), owners(root), tested_ids(root)
    problems = [f"{r}: no test case in spec/modules/*/tests.md" for r in sorted(required - tested)]
    for req in sorted(required):
        modules = owned.get(req, [])
        if len(modules) != 1:
            problems.append(f"{req}: owned by {len(modules)} modules {modules} in plan §2")
    problems += [
        f"{r}: owned in plan §2 but not in root §18" for r in sorted(set(owned) - required)
    ]
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    problems = check(root)
    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"trace check failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"trace check ok: {len(required_ids(root))} requirements, each tested and singly owned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
