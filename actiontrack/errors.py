"""Typed errors and the process exit codes they map to (root spec §12)."""

from __future__ import annotations

from enum import IntEnum
from typing import ClassVar


class ExitCode(IntEnum):
    OK = 0
    FATAL = 1
    USER = 2
    EXTERNAL = 3
    INTERRUPTED = 130


class ActionTrackError(Exception):
    """Base for every error the CLI turns into a readable message and an exit code."""

    exit_code: ClassVar[ExitCode] = ExitCode.FATAL

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class FatalError(ActionTrackError):
    """Unrecoverable problem: missing folder, DB not writable, unimplemented command."""


class UserInputError(ActionTrackError):
    """Bad ID, owner, filter, flag value or config."""

    exit_code = ExitCode.USER


class ExternalServiceError(ActionTrackError):
    """An external service (the Gmail MCP server) failed."""

    exit_code = ExitCode.EXTERNAL


class ForbiddenToolError(ActionTrackError):
    """A non-allowlisted MCP tool was about to be called. A programming error; must never happen."""
