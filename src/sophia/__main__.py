"""CLI entry point for Sophia."""

from __future__ import annotations

import cyclopts

import sophia
from sophia.infra.logging import setup_logging

app = cyclopts.App(
    name="sophia",
    help="Σοφία — A student toolkit for TU Wien's TUWEL.",
    version=sophia.__version__,
    help_epilogue="Run 'sophia <command> --help' for details on any command.",
)

# Mount sub-apps
from sophia.cli.auth import app as auth_app  # noqa: E402
from sophia.cli.books import app as books_app  # noqa: E402
from sophia.cli.deadlines import app as deadlines_app  # noqa: E402
from sophia.cli.jobs import app as jobs_app  # noqa: E402
from sophia.cli.lectures import app as lectures_app  # noqa: E402
from sophia.cli.quickstart import app as quickstart_app  # noqa: E402
from sophia.cli.register import app as register_app  # noqa: E402
from sophia.cli.run_job import register_run_job  # noqa: E402
from sophia.cli.status import register_status  # noqa: E402
from sophia.cli.study import app as study_app  # noqa: E402

app.command(books_app)
app.command(auth_app)
app.command(deadlines_app)
app.command(register_app)
app.command(lectures_app)
app.command(jobs_app)
app.command(study_app)
app.command(quickstart_app)
register_run_job(app)
register_status(app)

# Shell completion (sophia --install-completion)
app.register_install_completion_command()  # type: ignore[reportUnknownMemberType]


def main() -> None:
    """Entry point called by the `sophia` console script."""
    import os
    import sys

    from sophia.cli._output import handle_cli_error, output

    args = sys.argv[1:]

    # Parse global flags before cyclopts sees them
    output.json_mode = "--json" in args
    output.quiet = "--quiet" in args or "-q" in args
    output.no_color = "--no-color" in args or bool(os.environ.get("NO_COLOR"))
    output.debug = "--debug" in args

    for flag in ("--json", "--quiet", "-q", "--no-color", "--debug"):
        while flag in args:
            args.remove(flag)

    setup_logging(debug=output.debug)

    try:
        app(args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        handle_cli_error(exc)


if __name__ == "__main__":
    main()
