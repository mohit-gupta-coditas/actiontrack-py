from __future__ import annotations

import io
import logging
import subprocess
import sys

import pytest

from actiontrack.console import _ConsoleHandler, configure_stdio_utf8, make_output


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_TC_M0_19_no_color_env_on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    tty = FakeTTY()
    monkeypatch.setattr(sys, "stdout", tty)
    output = make_output(no_color=False, quiet=False, verbosity=0, env={"NO_COLOR": "1"})
    assert output.out.is_terminal
    output.out.print("[bold red]overdue[/bold red]")
    assert "\x1b" not in tty.getvalue()
    assert "overdue" in tty.getvalue()


def test_no_color_flag_disables_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    tty = FakeTTY()
    monkeypatch.setattr(sys, "stdout", tty)
    output = make_output(no_color=True, quiet=False, verbosity=0, env={})
    output.out.print("[red]x[/red]")
    assert "\x1b" not in tty.getvalue()


def test_TC_M0_20_non_tty_stream_disables_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = io.StringIO()
    monkeypatch.setattr(sys, "stdout", pipe)
    output = make_output(no_color=False, quiet=False, verbosity=0, env={})
    assert not output.out.is_terminal
    output.out.print("[red]x[/red]")
    assert pipe.getvalue() == "x\n"


def test_TC_M0_21_quiet_keeps_only_errors(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output(no_color=True, quiet=True, verbosity=0, env={})
    output.warn("x")
    output.info("y")
    output.error("z")
    captured = capsys.readouterr()
    assert captured.err == "Error: z\n"
    assert captured.out == ""


def test_info_and_warn_without_quiet(capsys: pytest.CaptureFixture[str]) -> None:
    output = make_output(no_color=True, quiet=False, verbosity=0, env={})
    output.info("y")
    output.warn("x")
    output.data("data")
    captured = capsys.readouterr()
    assert captured.err == "y\nWarning: x\n"
    assert captured.out == "data\n"


def test_TC_M0_22_debug_logging_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    make_output(no_color=True, quiet=False, verbosity=2, env={})
    logging.getLogger("actiontrack.test").debug("dbg-record")
    captured = capsys.readouterr()
    assert "dbg-record" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("quiet", "verbosity", "level"),
    [(False, 0, logging.WARNING), (False, 1, logging.INFO), (True, 2, logging.ERROR)],
)
def test_log_levels(quiet: bool, verbosity: int, level: int) -> None:
    make_output(no_color=True, quiet=quiet, verbosity=verbosity, env={})
    logger = logging.getLogger("actiontrack")
    assert logger.level == level
    ours = [h for h in logger.handlers if isinstance(h, _ConsoleHandler)]
    assert len(ours) == 1  # reconfiguring replaces, never stacks


def test_TC_M0_24_utf8_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    out_buf, err_buf = io.BytesIO(), io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(out_buf, encoding="cp1252", newline=""))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(err_buf, encoding="cp1252", newline=""))
    configure_stdio_utf8()
    print("⚠ Pérez")
    print("⚠ Pérez", file=sys.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    assert out_buf.getvalue().decode("utf-8") == "⚠ Pérez\n"
    assert err_buf.getvalue().decode("utf-8") == "⚠ Pérez\n"


def test_TC_M0_23_cli_import_is_lazy() -> None:
    code = (
        "import sys, actiontrack.cli; "
        "print(sorted(m for m in ('dateparser', 'rapidfuzz', 'mcp', 'jinja2') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
