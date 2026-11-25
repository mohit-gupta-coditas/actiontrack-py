from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from actiontrack import __version__, cli
from actiontrack.cli import AppContext, create_app, run
from actiontrack.errors import ExternalServiceError, UserInputError


def app_raising(exc: BaseException) -> typer.Typer:
    app = create_app()

    @app.command()
    def boom() -> None:
        raise exc

    return app


def test_TC_M0_01_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--version"]) == 0
    assert capsys.readouterr().out == f"actiontrack {__version__}\n"


def test_TC_M0_02_python_m_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "actiontrack", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout == f"actiontrack {__version__}\n"


def test_TC_M0_03_no_args_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert run([]) == 0
    out = capsys.readouterr().out
    assert "Usage" in out
    for command in ("ingest", "list", "done", "followup", "config"):
        assert command in out


def test_config_group_without_subcommand_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["config"]) == 0
    assert "show" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [["ingest"], ["list"], ["done"], ["followup"], ["config", "show"]],
    ids=lambda a: " ".join(a),
)
def test_TC_M0_04_help_has_examples(args: list[str]) -> None:
    result = CliRunner().invoke(cli.app, [*args, "--help"])
    assert result.exit_code == 0
    assert "Examples:" in result.stdout
    assert f"actiontrack {' '.join(args)}" in result.stdout


def test_short_help_option() -> None:
    result = CliRunner().invoke(cli.app, ["list", "-h"])
    assert result.exit_code == 0
    assert "Examples:" in result.stdout


def test_TC_M0_05_typo_suggestion(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["lst"]) == 2
    captured = capsys.readouterr()
    assert "Did you mean 'list'?" in captured.err
    assert captured.out == ""


def test_usage_error_for_bad_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list", "--nope"]) == 2
    assert "Error:" in capsys.readouterr().err


def test_TC_M0_09_missing_config_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.toml"
    assert run(["--config", str(missing), "list"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error:")
    assert str(missing) in err


def test_TC_M0_11_config_show_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACTIONTRACK_EMAIL_DOMAIN", "example.org")
    assert run(["config", "show", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)  # nothing but JSON on stdout
    assert data["email_domain"] == {"value": "example.org", "source": "env"}
    assert data["fuzzy_threshold"] == {"value": 88, "source": "default"}
    assert data["gmail_mcp"]["value"]["draft_tool"] == "create_draft"
    assert data["schema_version"] == 1


def test_config_show_table_with_db_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--no-color", "--db", str(tmp_path / "x.db"), "config", "show"]) == 0
    out = capsys.readouterr().out
    assert "fuzzy_threshold" in out
    assert "flag" in out


def test_TC_M0_12_user_error_message_and_hint(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["boom"], app_=app_raising(UserInputError("bad", hint="try x"))) == 2
    err = capsys.readouterr().err
    assert "Error: bad\nHint: try x\n" in err
    assert "Traceback" not in err


def test_TC_M0_13_debug_shows_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    app = app_raising(UserInputError("bad", hint="try x"))
    assert run(["--debug", "boom"], app_=app) == 2
    assert "Traceback" in capsys.readouterr().err


def test_debug_env_shows_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    app = app_raising(ValueError("x"))
    assert run(["boom"], app_=app, env={"ACTIONTRACK_DEBUG": "1"}) == 1
    assert "Traceback" in capsys.readouterr().err


def test_TC_M0_14_external_error_exit_3(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["boom"], app_=app_raising(ExternalServiceError("mcp down"))) == 3
    assert "Error: mcp down" in capsys.readouterr().err


def test_TC_M0_15_keyboard_interrupt(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["boom"], app_=app_raising(KeyboardInterrupt())) == 130
    assert "Interrupted" in capsys.readouterr().err


def test_TC_M0_16_unexpected_exception(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["boom"], app_=app_raising(ValueError("secret detail"))) == 1
    err = capsys.readouterr().err
    assert "internal error (ValueError)" in err
    assert "Traceback" not in err
    assert "secret detail" not in err


@pytest.mark.parametrize("args", [["followup", "priya"]])
def test_TC_M0_27_stub_commands(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert run(args) == 1
    assert "Error: not implemented" in capsys.readouterr().err


def test_callback_builds_app_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIONTRACK_TODAY", "2026-11-18")
    seen: list[AppContext] = []
    app = create_app()

    @app.command()
    def probe(ctx: typer.Context) -> None:
        seen.append(ctx.obj)

    assert run(["-q", "-vv", "--debug", "probe"], app_=app) == 0
    (app_ctx,) = seen
    assert app_ctx.clock.today().isoformat() == "2026-11-18"
    assert app_ctx.debug
    assert app_ctx.output.quiet
    assert app_ctx.output.verbosity == 2


def test_main_exits_with_run_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["actiontrack", "--version"])
    monkeypatch.setattr(cli, "configure_stdio_utf8", lambda: None)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
