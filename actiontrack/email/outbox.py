"""The outbox: a rendered email saved as `.eml` when no Gmail draft was created (REQ-MCP-04)."""

from __future__ import annotations

import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

STATUS_HEADER = "X-Actiontrack-Status"
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def write_outbox(
    *, outbox_dir: Path, owner_key: str, to: str, subject: str, body: str, now: datetime
) -> Path:
    """Write an RFC 5322 message to a new file in `outbox_dir`. Never overwrites."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = format_datetime(now)
    msg[STATUS_HEADER] = "draft-not-created"
    msg.set_content(body)
    data = msg.as_bytes(policy=msg.policy.clone(linesep="\r\n"))

    outbox_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{owner_slug(owner_key)}-{now:%Y%m%dT%H%M%S}"
    n = 1
    while True:
        path = outbox_dir / f"{stem}{f'-{n}' if n > 1 else ''}.eml"
        try:
            with path.open("xb") as fh:
                fh.write(data)
        except FileExistsError:
            n += 1
            continue
        return path


def owner_slug(owner_key: str) -> str:
    """A filename-safe owner key: `name:Priya` → `name-priya` (G17)."""
    return _UNSAFE.sub("-", owner_key.lower()).strip("-.") or "unknown"
