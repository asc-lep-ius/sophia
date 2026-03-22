"""Unified academic landscape — sophia plan."""

from __future__ import annotations

from typing import Annotated

import cyclopts

app = cyclopts.App(name="plan", help="Your academic landscape — see what's on your plate.")


@app.default
async def plan_default(
    *,
    horizon: Annotated[
        int, cyclopts.Parameter(help="Days ahead for deadlines.", name="--horizon")
    ] = 14,
    limit: Annotated[int, cyclopts.Parameter(help="Max items to show.", name="--limit")] = 15,
) -> None:
    """Show your academic landscape: deadlines, due reviews, confidence gaps.

    This is YOUR view of YOUR situation. The ranking is a starting point —
    you decide what matters most right now.
    """
    from datetime import UTC, datetime

    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.domain.models import PlanItemType
    from sophia.infra.di import create_app
    from sophia.services.athena_chronos import build_plan_items

    console = Console()

    TYPE_STYLES = {
        PlanItemType.DEADLINE: ("bold red", "deadline"),
        PlanItemType.REVIEW: ("bold cyan", "review"),
        PlanItemType.CONFIDENCE_GAP: ("bold yellow", "gap"),
    }

    try:
        async with create_app() as container:
            items = await build_plan_items(container.db, horizon_days=horizon)

            if not items:
                console.print("[dim]Nothing on the radar. Enjoy the quiet.[/dim]")
                return

            items = items[:limit]

            table = Table(
                title="Your landscape",
                caption="Ranked by composite score — disagree? Good. You decide.",
            )
            table.add_column("#", style="dim", width=3)
            table.add_column("Type", width=10)
            table.add_column("Item", style="bold")
            table.add_column("Course")
            table.add_column("Due", style="dim")
            table.add_column("Detail")
            table.add_column("Score", justify="right", style="dim")

            for i, item in enumerate(items, 1):
                style, type_label = TYPE_STYLES.get(item.item_type, ("", item.item_type.value))
                due_str = ""
                if item.due_at:
                    try:
                        due_dt = datetime.fromisoformat(item.due_at)
                        days_until = (due_dt - datetime.now(UTC)).days
                        due_str = f"{days_until}d" if days_until >= 0 else f"{abs(days_until)}d ago"
                    except ValueError:
                        due_str = item.due_at[:10]

                table.add_row(
                    str(i),
                    f"[{style}]{type_label}[/{style}]",
                    item.title,
                    item.course_name,
                    due_str,
                    item.detail,
                    f"{item.score:.2f}",
                )

            console.print(table)
            console.print()

            deadlines = sum(1 for i in items if i.item_type == PlanItemType.DEADLINE)
            reviews = sum(1 for i in items if i.item_type == PlanItemType.REVIEW)
            gaps = sum(1 for i in items if i.item_type == PlanItemType.CONFIDENCE_GAP)
            parts = []
            if deadlines:
                parts.append(f"{deadlines} deadline(s)")
            if reviews:
                parts.append(f"{reviews} review(s) due")
            if gaps:
                parts.append(f"{gaps} confidence gap(s)")
            console.print(f"[dim]{', '.join(parts)}[/dim]")

            console.print(
                "\n[dim]This is your landscape, not your orders. "
                "The score ranks by urgency and gaps — "
                "but only you know what matters most right now.[/dim]"
            )
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None
