"""Typer app: argument parsing, output formatting and exception → exit-code mapping only.

Heavy dependencies (dateparser, rapidfuzz, mcp, jinja2) must only be imported inside command
functions, never at module level here or in anything imported from here (REQ-CLI-08).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table

# Typer vendors Click; its ClickException (usage errors, bad parameters) is not re-exported.
from typer._click.exceptions import ClickException

from actiontrack import __version__
from actiontrack.clock import Clock, clock_from_env
from actiontrack.config import Config, load_config, settings_view
from actiontrack.console import Output, configure_stdio_utf8, make_output
from actiontrack.errors import ActionTrackError, ExitCode, FatalError, UserInputError
from actiontrack.models import JSON_SCHEMA_VERSION, to_jsonable

PROG_NAME = "actiontrack"
DEBUG_ENV = "ACTIONTRACK_DEBUG"
CONTEXT_SETTINGS: dict[str, Any] = {"help_option_names": ["-h", "--help"]}


@dataclass
class AppContext:
    config: Config
    output: Output
    clock: Clock
    debug: bool


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"{PROG_NAME} {__version__}")
        raise typer.Exit()


def _app_callback(
    ctx: typer.Context,
    db: Annotated[
        Path | None, typer.Option("--db", help="SQLite database path.", show_default=False)
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="Config file (TOML).", show_default=False)
    ] = None,
    verbose: Annotated[
        int, typer.Option("--verbose", "-v", count=True, help="More logging (-v INFO, -vv DEBUG).")
    ] = 0,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Only data and errors.")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colour.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Show full tracebacks on errors.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            is_eager=True,
            callback=_version_callback,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Extract, track and follow up on action items from meeting notes."""
    if ctx.resilient_parsing:
        return
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
    env = os.environ
    output = make_output(no_color=no_color, quiet=quiet, verbosity=verbose, env=env)
    ctx.obj = AppContext(
        config=load_config(flags={"db_path": db}, env=env, config_path=config),
        output=output,
        clock=clock_from_env(env),
        debug=debug or env.get(DEBUG_ENV) == "1",
    )


def create_app() -> typer.Typer:
    """Build the app. Tests build their own instance to register throwaway commands."""
    app = typer.Typer(
        name=PROG_NAME,
        context_settings=CONTEXT_SETTINGS,
        invoke_without_command=True,
        pretty_exceptions_enable=False,
        add_completion=True,
    )
    app.callback()(_app_callback)

    @app.command()
    def ingest(
        ctx: typer.Context,
        folder: Annotated[Path, typer.Argument(help="Folder of meeting notes (*.md).")],
        recursive: Annotated[
            bool,
            typer.Option("--recursive/--no-recursive", help="Also read notes in sub-folders."),
        ] = True,
        no_fuzzy: Annotated[
            bool, typer.Option("--no-fuzzy", help="Merge exact duplicates only, for this run.")
        ] = False,
        report_json: Annotated[
            Path | None,
            typer.Option(
                "--report-json",
                metavar="PATH",
                help="Also write the report as JSON to PATH.",
                show_default=False,
            ),
        ] = None,
    ) -> None:
        """Ingest meeting notes and update the action item store.

        Extracts action items from every Markdown note in FOLDER and merges duplicates.

        Unchanged files are skipped, so re-running is safe. Notes that can't be parsed are
        listed in the report and the run carries on.

        \b
        Examples:
          actiontrack ingest ./notes
          actiontrack ingest ./notes --no-recursive
          actiontrack -v ingest ./notes --report-json report.json
        """
        app_ctx: AppContext = ctx.find_root().obj
        _ingest(
            app_ctx,
            folder,
            recursive=recursive,
            fuzzy_enabled=False if no_fuzzy else None,
            report_json=report_json,
        )

    @app.command("list")
    def list_items() -> None:
        """List action items.

        By default shows open items sorted by due date, then owner.

        \b
        Examples:
          actiontrack list
          actiontrack list --owner priya --status overdue
          actiontrack list --json
        """
        raise FatalError("not implemented")

    @app.command()
    def done(
        item_id: Annotated[str, typer.Argument(metavar="ID", help="Item ID or unique prefix.")],
    ) -> None:
        """Mark an action item as done.

        ID may be any unique prefix of the item ID shown by `list`.

        \b
        Examples:
          actiontrack done a3f91c
          actiontrack done a3f
        """
        raise FatalError("not implemented")

    @app.command()
    def followup(
        owner: Annotated[str, typer.Argument(help="Person key, email, full or first name.")],
    ) -> None:
        """Draft a follow-up email to an owner about their open items.

        Creates a Gmail draft (it never sends) with the owner's overdue and open items.

        \b
        Examples:
          actiontrack followup priya
          actiontrack followup "Rahul Sharma" --dry-run
        """
        raise FatalError("not implemented")

    config_app = typer.Typer(
        context_settings=CONTEXT_SETTINGS,
        help="Inspect the effective configuration.",
        invoke_without_command=True,
    )
    app.add_typer(config_app, name="config")

    @config_app.callback()
    def config_callback(ctx: typer.Context) -> None:
        """Inspect the effective configuration."""
        if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
            typer.echo(ctx.get_help())
            raise typer.Exit()

    @config_app.command("show")
    def config_show(
        ctx: typer.Context,
        as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    ) -> None:
        """Show the effective configuration and where each value came from.

        Sources, highest precedence first: flag, env (ACTIONTRACK_*), file, default.

        \b
        Examples:
          actiontrack config show
          actiontrack config show --json
        """
        app_ctx: AppContext = ctx.find_root().obj
        _config_show(app_ctx, as_json=as_json)

    return app


def _config_show(app_ctx: AppContext, *, as_json: bool) -> None:
    view = settings_view(app_ctx.config)
    output = app_ctx.output
    if as_json:
        data: dict[str, Any] = {"schema_version": JSON_SCHEMA_VERSION}
        data.update(
            {
                key: {"value": to_jsonable(value), "source": source}
                for key, (value, source) in view.items()
            }
        )
        output.data(json.dumps(data, indent=2, ensure_ascii=False))
        return
    table = Table("Key", "Value", "Source")
    for key, (value, source) in view.items():
        shown = to_jsonable(value)
        table.add_row(key, shown if isinstance(shown, str) else json.dumps(shown), source)
    output.out.print(table)


def _ingest(
    app_ctx: AppContext,
    folder: Path,
    *,
    recursive: bool,
    fuzzy_enabled: bool | None,
    report_json: Path | None,
) -> None:
    from actiontrack.dedup import shortest_unique_prefixes
    from actiontrack.services.ingest import LOGGER_NAME, check_folder, format_report, run_ingest
    from actiontrack.store.db import connect
    from actiontrack.store.repo import ItemRepo

    output = app_ctx.output
    check_folder(folder)  # before connect, so a mistyped folder doesn't create a database
    if app_ctx.debug:
        logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG)  # per-file tracebacks
    conn = connect(app_ctx.config.db_path)
    try:
        show_progress = output.err.is_terminal and not output.quiet
        report = run_ingest(
            folder,
            recursive=recursive,
            conn=conn,
            cfg=app_ctx.config,
            clock=app_ctx.clock,
            fuzzy_enabled=fuzzy_enabled,
            progress=_RichProgress(output.err) if show_progress else None,
        )
        short_ids = shortest_unique_prefixes(ItemRepo(conn).ids())
    finally:
        conn.close()

    lines = format_report(
        report,
        quiet=output.quiet,
        verbose=output.verbosity > 0,
        short_ids=short_ids,
        cwd=Path.cwd(),
    )
    for line in lines:
        output.data(line)
    if report_json is not None:
        text = json.dumps(report.to_json(), indent=2, ensure_ascii=False) + "\n"
        try:
            report_json.write_text(text, encoding="utf-8")
        except OSError as e:
            raise UserInputError(
                f"cannot write the JSON report to {report_json}: {e.strerror or e}"
            ) from e


class _RichProgress:
    """`ProgressSink` drawing a transient bar on stderr (REQ-INGEST-09)."""

    def __init__(self, console: Console) -> None:
        self._progress = Progress(
            TextColumn("Ingesting"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.fields[name]}"),
            console=console,
            transient=True,
        )
        self._task = self._progress.add_task("ingest", total=None, name="")

    def start(self, total: int) -> None:
        self._progress.update(self._task, total=total)
        self._progress.start()

    def advance(self, path: Path) -> None:
        self._progress.update(self._task, advance=1, name=path.name)

    def finish(self) -> None:
        self._progress.stop()


app = create_app()


def run(
    argv: Sequence[str] | None = None,
    *,
    app_: typer.Typer | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run the CLI and return the exit code. All error → exit-code mapping lives here."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    debug = "--debug" in args or env.get(DEBUG_ENV) == "1"
    command = typer.main.get_command(app_ if app_ is not None else app)
    try:
        rv = command.main(args=args, prog_name=PROG_NAME, standalone_mode=False)
    except ActionTrackError as e:
        _report(f"Error: {e.message}", debug=debug)
        if e.hint:
            _err(f"Hint: {e.hint}")
        return int(e.exit_code)
    except ClickException as e:
        _err(f"Error: {e.format_message()}")
        _err(f"Run '{PROG_NAME} --help' for usage.")
        return e.exit_code
    except (KeyboardInterrupt, typer.Abort):
        _err("Interrupted")
        return int(ExitCode.INTERRUPTED)
    except Exception as e:
        _report(
            f"Error: internal error ({type(e).__name__}). Re-run with --debug for details.",
            debug=debug,
        )
        return int(ExitCode.FATAL)
    # Typer turns Ctrl-C into a silent Exit(130), which standalone_mode=False returns.
    if rv == ExitCode.INTERRUPTED:
        _err("Interrupted")
    return rv if isinstance(rv, int) else int(ExitCode.OK)


def main() -> None:
    configure_stdio_utf8()
    sys.exit(run())


def _report(message: str, *, debug: bool) -> None:
    if debug:
        traceback.print_exc(file=sys.stderr)
    _err(message)


def _err(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.stderr.flush()
