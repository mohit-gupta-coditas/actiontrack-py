"""stdout/stderr consoles and logging (REQ-CLI-03, REQ-CLI-04, REQ-CLI-09).

stdout carries data only; messages, warnings, progress and logs go to stderr.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from rich.console import Console

LOGGER_NAME = "actiontrack"


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
    out = Console(color_system=color_system, no_color=not color, highlight=False)
    err = Console(stderr=True, color_system=color_system, no_color=not color, highlight=False)
    output = Output(out=out, err=err, quiet=quiet, verbosity=verbosity)
    _configure_logging(output)
    return output


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
