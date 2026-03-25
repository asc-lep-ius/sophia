"""Chart with accessible data table toggle for screen readers."""

from __future__ import annotations

from typing import Any

from nicegui import ui


def chart_with_table(
    chart_config: dict[str, Any],
    *,
    headers: list[str],
    rows: list[list[str]],
    chart_id: str = "",
) -> None:
    """Render an EChart with a toggleable accessible data table.

    Screen readers and users who cannot interpret charts can toggle the
    table view to access the same data in tabular form.
    """
    ui.echart(chart_config)
    show_table = ui.switch("Show as table").props(
        f'aria-label="Toggle data table view for {chart_id}"'
    )
    with ui.column().bind_visibility_from(show_table, "value"):  # pyright: ignore[reportUnknownMemberType]
        _render_accessible_table(headers=headers, rows=rows, table_id=chart_id)


def _render_accessible_table(
    *,
    headers: list[str],
    rows: list[list[str]],
    table_id: str,
) -> None:
    """Render an HTML table with proper headers for screen readers."""
    with (
        ui.element("table")
        .classes("w-full border-collapse text-sm mt-2")
        .props(f'aria-label="Data table for {table_id}"')
    ):
        with ui.element("thead"), ui.element("tr").classes("border-b"):
            for header in headers:
                with ui.element("th").classes("text-left p-2 font-semibold"):
                    ui.label(header)
        with ui.element("tbody"):
            for row in rows:
                with ui.element("tr").classes("border-b"):
                    for cell in row:
                        with ui.element("td").classes("p-2"):
                            ui.label(cell)
