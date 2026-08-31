"""sophia status — cross-course overview dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Table, case, distinct, func, select

from sophia.infra.schema import (
    knowledge_index,
    lecture_downloads,
    review_schedule,
    student_flashcards,
    topic_mappings,
    transcriptions,
)

if TYPE_CHECKING:
    import cyclopts
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import Case, ColumnElement
    from sqlalchemy.sql.selectable import ScalarSelect


def register_status(app: cyclopts.App) -> None:
    """Register the 'sophia status' command on *app*."""

    @app.command(name="status")
    async def _status() -> None:  # pyright: ignore[reportUnusedFunction]
        """Show a cross-course overview: lectures, topics, flashcards, and reviews due."""
        from rich.table import Table

        from sophia.cli._output import print_json_or_table
        from sophia.domain.errors import AuthError
        from sophia.infra.di import create_app

        try:
            async with create_app() as container, container.session() as db:
                data = await _fetch_course_stats(db)
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


async def _fetch_course_stats(db: AsyncSession) -> list[dict[str, int | str | None]]:
    """Aggregate per-module stats from the DB in two queries."""

    def completed(column: ColumnElement[str | None]) -> Case[int]:
        return case((column == "completed", 1), else_=0)

    def scoped_count(table: Table) -> ScalarSelect[int]:
        return (
            select(func.count())
            .select_from(table)
            .where(table.c.course_id == lecture_downloads.c.module_id)
            .scalar_subquery()
        )

    primary_rows = (
        await db.execute(
            select(
                lecture_downloads.c.module_id,
                func.count(distinct(lecture_downloads.c.episode_id)).label("total_lectures"),
                func.sum(completed(lecture_downloads.c.status)).label("downloaded"),
                func.sum(completed(transcriptions.c.status)).label("transcribed"),
                func.sum(completed(knowledge_index.c.status)).label("indexed"),
                scoped_count(topic_mappings).label("topics"),
                scoped_count(student_flashcards).label("flashcards"),
            )
            .select_from(lecture_downloads)
            .outerjoin(
                transcriptions,
                lecture_downloads.c.episode_id == transcriptions.c.episode_id,
            )
            .outerjoin(
                knowledge_index,
                lecture_downloads.c.episode_id == knowledge_index.c.episode_id,
            )
            .group_by(lecture_downloads.c.module_id)
            .order_by(lecture_downloads.c.module_id)
        )
    ).all()

    if not primary_rows:
        return []

    now = func.now()
    review_rows = (
        await db.execute(
            select(
                review_schedule.c.course_id,
                func.sum(case((review_schedule.c.next_review_at <= now, 1), else_=0)).label(
                    "due_today"
                ),
                func.min(
                    case((review_schedule.c.next_review_at > now, review_schedule.c.next_review_at))
                ).label("next_review"),
            ).group_by(review_schedule.c.course_id)
        )
    ).all()
    review_map: dict[int, tuple[int, str | None]] = {
        int(row.course_id): (
            int(row.due_today or 0),
            row.next_review.isoformat() if row.next_review else None,
        )
        for row in review_rows
    }

    result: list[dict[str, int | str | None]] = []
    for row in primary_rows:
        record: dict[str, int | str | None] = dict(row._mapping)  # noqa: SLF001 — Row mapping view
        module_id = int(record["module_id"])  # type: ignore[arg-type]
        due, next_rev = review_map.get(module_id, (0, None))
        record["due_today"] = due
        record["next_review"] = next_rev
        result.append(record)

    return result
