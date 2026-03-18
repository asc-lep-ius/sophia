"""sophia status — cross-course overview dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite
    import cyclopts


def register_status(app: cyclopts.App) -> None:
    """Register the 'sophia status' command on *app*."""

    @app.command(name="status")
    async def _status() -> None:
        """Show a cross-course overview: lectures, topics, flashcards, and reviews due."""
        from rich.table import Table

        from sophia.cli._output import print_json_or_table
        from sophia.domain.errors import AuthError
        from sophia.infra.di import create_app

        try:
            async with create_app() as container:
                data = await _fetch_course_stats(container.db)
        except AuthError:
            from rich.console import Console

            Console().print("[red]Not logged in — run:[/red] sophia auth login")
            raise SystemExit(1) from None

        if not data:
            from rich.console import Console

            Console().print(
                "[yellow]No data yet.[/yellow] "
                "Run: [cyan]sophia lectures process <module-id>[/cyan]"
            )
            return

        table = Table(title="Sophia Status", show_lines=True)
        table.add_column("Module", style="cyan", justify="right")
        table.add_column("Episodes", justify="right")
        table.add_column("Transcribed", justify="right")
        table.add_column("Indexed", justify="right")
        table.add_column("Topics", justify="right")
        table.add_column("Cards", justify="right")
        table.add_column("Due Today", justify="right")
        table.add_column("Next Review", justify="center")

        for row in data:
            due = int(row["due_today"] or 0)
            due_cell = f"[red bold]{due}[/red bold]" if due > 0 else "[dim]0[/dim]"
            next_rev = (str(row["next_review"]) if row["next_review"] else "—")[:10]
            total = int(row["total_lectures"] or 0)

            table.add_row(
                str(row["module_id"]),
                f"{row['downloaded']}/{total}",
                _frac_cell(int(row["transcribed"] or 0), total),
                _frac_cell(int(row["indexed"] or 0), total),
                str(row["topics"]),
                str(row["flashcards"]),
                due_cell,
                next_rev,
            )

        print_json_or_table(data, table=table)


def _frac_cell(count: int, total: int) -> str:
    """Format count/total with colour: green=complete, yellow=partial, dim=zero."""
    if total == 0:
        return "[dim]—[/dim]"
    if count == total:
        return f"[green]{count}/{total}[/green]"
    if count == 0:
        return f"[dim]0/{total}[/dim]"
    return f"[yellow]{count}/{total}[/yellow]"


async def _fetch_course_stats(db: aiosqlite.Connection) -> list[dict[str, int | str | None]]:
    """Aggregate per-module stats from the DB in two queries."""
    cursor = await db.execute(
        "SELECT"
        "  ld.module_id,"
        "  COUNT(DISTINCT ld.episode_id) AS total_lectures,"
        "  SUM(CASE WHEN ld.status  = 'completed' THEN 1 ELSE 0 END) AS downloaded,"
        "  SUM(CASE WHEN t.status   = 'completed' THEN 1 ELSE 0 END) AS transcribed,"
        "  SUM(CASE WHEN ki.status  = 'completed' THEN 1 ELSE 0 END) AS indexed,"
        "  (SELECT COUNT(*) FROM topic_mappings"
        "     WHERE course_id = ld.module_id) AS topics,"
        "  (SELECT COUNT(*) FROM student_flashcards"
        "     WHERE course_id = ld.module_id) AS flashcards"
        " FROM lecture_downloads ld"
        " LEFT JOIN transcriptions  t  ON ld.episode_id = t.episode_id"
        " LEFT JOIN knowledge_index ki ON ld.episode_id = ki.episode_id"
        " GROUP BY ld.module_id"
        " ORDER BY ld.module_id"
    )
    primary_rows = await cursor.fetchall()
    cols = [col[0] for col in cursor.description]

    if not primary_rows:
        return []

    cursor = await db.execute(
        "SELECT"
        "  course_id,"
        "  SUM(CASE WHEN next_review_at <= datetime('now') THEN 1 ELSE 0 END)"
        "    AS due_today,"
        "  MIN(CASE WHEN next_review_at  > datetime('now') THEN next_review_at END)"
        "    AS next_review"
        " FROM review_schedule"
        " GROUP BY course_id"
    )
    review_map: dict[int, tuple[int, str | None]] = {
        int(row[0]): (int(row[1]), row[2]) for row in await cursor.fetchall()
    }

    result: list[dict[str, int | str | None]] = []
    for raw in primary_rows:
        record: dict[str, int | str | None] = dict(zip(cols, raw, strict=True))
        module_id = int(record["module_id"])
        due, next_rev = review_map.get(module_id, (0, None))
        record["due_today"] = due
        record["next_review"] = next_rev
        result.append(record)

    return result
