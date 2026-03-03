"""CLI entry point for Sophia."""

from __future__ import annotations

import cyclopts

import sophia
from sophia.infra.logging import setup_logging

app = cyclopts.App(
    name="sophia",
    help="Σοφία — A student toolkit for TU Wien's TUWEL.",
    version=sophia.__version__,
)

books_app = cyclopts.App(name="books", help="Book discovery and download commands.")
app.command(books_app)


@books_app.command
def discover() -> None:
    """Discover book references from enrolled TUWEL courses."""
    import structlog

    log = structlog.get_logger()
    log.info("books_discover_not_implemented", msg="Not yet implemented")


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
