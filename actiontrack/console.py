"""stdout/stderr consoles and logging (REQ-CLI-03, REQ-CLI-04, REQ-CLI-09).

stdout carries data only; messages, warnings, progress and logs go to stderr.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rich.console import Console

LOGGER_NAME = "actiontrack"


class StdoutClosed(Exception):
    """The reader of stdout went away (`actiontrack list | head -3`) (G36)."""


class _Console(Console):
    def on_broken_pipe(self) -> None:
        # rich's default exits 1; the CLI boundary turns this into a quiet exit 0 instead.
        self.quiet = True
        raise StdoutClosed


@dataclass
class Output:
    out: Console  # stdout — data only
    err: Console  # stderr — messages, warnings, progress, logs
    quiet: bool
    verbosity: int  # 0 WARNING, 1 INFO, 2+ DEBUG

    def data(self, text: str) -> None:
        """Write plain data to stdout, unwrapped and without markup."""
        self.out.print(text, markup=False, highlight=False, soft_wrap=True)

    def info(self, message: str) -> None:
        if not self.quiet:
            self.err.print(message, markup=False, highlight=False, soft_wrap=True)

    def warn(self, message: str) -> None:
        if not self.quiet:
            self.err.print(f"Warning: {message}", markup=False, highlight=False, soft_wrap=True)

    def error(self, message: str) -> None:
        self.err.print(f"Error: {message}", markup=False, highlight=False, soft_wrap=True)


def color_enabled(*, no_color: bool, env: Mapping[str, str]) -> bool:
    """Colour unless `--no-color` or a non-empty NO_COLOR. TTY detection is left to rich."""
    return not no_color and not env.get("NO_COLOR")


def make_output(*, no_color: bool, quiet: bool, verbosity: int, env: Mapping[str, str]) -> Output:
    # No `file=`: rich resolves sys.stdout/sys.stderr at write time, and emits no
    # colour when the stream is not a terminal.
    color = color_enabled(no_color=no_color, env=env)
    color_system: Literal["auto"] | None = "auto" if color else None
    # Forced colour must be ANSI: legacy Win32 console calls never reach a pipe (G35).
    legacy_windows = False if env.get("FORCE_COLOR") else None
    out = _Console(
        color_system=color_system,
        no_color=not color,
        highlight=False,
        legacy_windows=legacy_windows,
    )
    err = _Console(
        stderr=True,
        color_system=color_system,
        no_color=not color,
        highlight=False,
        legacy_windows=legacy_windows,
    )
    output = Output(out=out, err=err, quiet=quiet, verbosity=verbosity)
    _configure_logging(output)
    return output


def stdout_closed(error: BaseException) -> bool:
    """Whether `error` means the reader of stdout has gone (G36)."""
    if isinstance(error, StdoutClosed | BrokenPipeError):
        return True
    if not isinstance(error, OSError):
        return False
    try:  # on Windows a closed pipe raises OSError(EINVAL); the pending write fails again
        sys.stdout.flush()
    except OSError:
        return True
    return False


def silence_stdout() -> None:
    """Point stdout at the null device, so the interpreter's final flush can't fail."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError):  # no real file descriptor (e.g. under test capture)
        pass


def configure_stdio_utf8() -> None:
    """Make stdout/stderr UTF-8 so accented names and the ⚠ marker print on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


class _ConsoleHandler(logging.Handler):
    def __init__(self, console: Console) -> None:
        super().__init__()
        self.console = console

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.console.print(self.format(record), markup=False, highlight=False, soft_wrap=True)
        except Exception:
            self.handleError(record)


def _log_level(*, quiet: bool, verbosity: int) -> int:
    if quiet:
        return logging.ERROR
    if verbosity >= 2:
        return logging.DEBUG
    if verbosity == 1:
        return logging.INFO
    return logging.WARNING


def _configure_logging(output: Output) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if isinstance(handler, _ConsoleHandler):
            logger.removeHandler(handler)
    handler = _ConsoleHandler(output.err)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(_log_level(quiet=output.quiet, verbosity=output.verbosity))
    logger.propagate = False
