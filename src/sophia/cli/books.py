"""Book discovery and download commands."""

from __future__ import annotations

import cyclopts

app = cyclopts.App(name="books", help="Book discovery and download commands.")


@app.command
async def discover() -> None:
    """Discover book references from enrolled TUWEL courses."""
    from rich.table import Table

    from sophia.cli._output import get_console, output, print_json_or_table
    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.pipeline import discover_books
    from sophia.services.reference_extractor import RegexReferenceExtractor

    console = get_console()

    try:
        async with create_app() as container:
            extractor = RegexReferenceExtractor()
            refs = await discover_books(
                courses=container.moodle,
                resources=container.moodle,
                extractor=extractor,
                metadata=container.tiss,
            )

            if not refs:
                console.print("[yellow]No book references found in enrolled courses.[/yellow]")
                return

            from sophia.services.pipeline import persist_references

            saved = await persist_references(container.db, refs)
    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None

    data = [
        {
            "title": ref.title or "—",
            "authors": ", ".join(ref.authors) if ref.authors else "—",
            "isbn": ref.isbn or "—",
            "source": ref.source.value,
            "course": ref.course_name or "—",
        }
        for ref in refs
    ]

    table = Table(title="Discovered Book References")
    table.add_column("Title", style="cyan", no_wrap=False)
    table.add_column("Author(s)", style="green")
    table.add_column("ISBN", style="magenta")
    table.add_column("Source", style="blue")
    table.add_column("Course", style="yellow", no_wrap=False)

    for row in data:
        table.add_row(row["title"], row["authors"], row["isbn"], row["source"], row["course"])

    print_json_or_table(data, table)
    if not output.json_mode:
        console.print(f"\n[dim]{saved} references persisted to database.[/dim]")
