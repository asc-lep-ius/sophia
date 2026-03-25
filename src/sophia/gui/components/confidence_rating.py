"""Confidence rating component — 1-5 buttons that map to DifficultyLevel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nicegui import ui

from sophia.domain.models import DifficultyLevel

if TYPE_CHECKING:
    from collections.abc import Callable

RATING_LABELS: Final[dict[int, str]] = {
    1: "No idea",
    2: "Guessing",
    3: "Partial",
    4: "Mostly right",
    5: "Certain",
}

_RATING_TO_DIFFICULTY: Final[dict[int, DifficultyLevel]] = {
    1: DifficultyLevel.CUED,
    2: DifficultyLevel.CUED,
    3: DifficultyLevel.EXPLAIN,
    4: DifficultyLevel.TRANSFER,
    5: DifficultyLevel.TRANSFER,
}

_DIFFICULTY_COLORS: Final[dict[DifficultyLevel, str]] = {
    DifficultyLevel.CUED: "red",
    DifficultyLevel.EXPLAIN: "orange",
    DifficultyLevel.TRANSFER: "green",
}


def rating_to_difficulty(rating: int) -> DifficultyLevel:
    """Map a 1-5 confidence rating to a ``DifficultyLevel``."""
    clamped = max(1, min(5, rating))
    return _RATING_TO_DIFFICULTY[clamped]


def confidence_rating(*, on_rate: Callable[[int], None]) -> None:
    """Render a 1-5 button group with labels and a difficulty tier badge.

    When the user clicks a rating, *on_rate* is called with the int (1-5)
    and the difficulty badge updates.
    """
    with ui.row().classes("gap-2 items-center"):
        for value, label in RATING_LABELS.items():
            ui.button(
                label,
                on_click=lambda _, v=value: _handle_click(v),
            ).props("outline dense")
        badge_label = ui.label("").classes("text-sm font-semibold ml-4")

    def _handle_click(rating: int) -> None:
        diff = rating_to_difficulty(rating)
        color = _DIFFICULTY_COLORS[diff]
        badge_label.text = diff.value.upper()
        badge_label.classes(replace=f"text-sm font-semibold ml-4 text-{color}-600")
        on_rate(rating)
