"""LaTeX assist palette — symbol buttons and template snippets.

Three assist levels auto-detected from the number of flashcards a student has
completed with LaTeX content:

* **Full**  (<10 cards): palette visible, template buttons, plain-text hints
* **Partial** (10–50 cards): palette collapsed, no auto-suggestions
* **Expert** (>50 cards): live preview only — no palette at all
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

# Thresholds for auto-detection
FULL_THRESHOLD: Final = 10
PARTIAL_THRESHOLD: Final = 50


class AssistLevel(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    EXPERT = "expert"


def detect_assist_level(
    flashcard_count: int,
    *,
    override: AssistLevel | None = None,
) -> AssistLevel:
    """Return the assist level for *flashcard_count*, or *override* if given."""
    if override is not None:
        return override
    if flashcard_count < FULL_THRESHOLD:
        return AssistLevel.FULL
    if flashcard_count <= PARTIAL_THRESHOLD:
        return AssistLevel.PARTIAL
    return AssistLevel.EXPERT


# Symbol groups shown at Full/Partial levels
GREEK_SYMBOLS: Final[dict[str, str]] = {
    "α": "\\alpha",
    "β": "\\beta",
    "γ": "\\gamma",
    "δ": "\\delta",
    "θ": "\\theta",
    "λ": "\\lambda",
    "π": "\\pi",
    "σ": "\\sigma",
    "Σ": "\\Sigma",
    "Ω": "\\Omega",
}

OPERATORS: Final[dict[str, str]] = {
    "±": "\\pm",
    "×": "\\times",
    "÷": "\\div",
    "≠": "\\neq",
    "≤": "\\leq",
    "≥": "\\geq",
    "≈": "\\approx",
    "∞": "\\infty",
}

CALCULUS: Final[dict[str, str]] = {
    "∫": "\\int",
    "∂": "\\partial",
    "∑": "\\sum",
    "∏": "\\prod",
    "√": "\\sqrt{}",
    "lim": "\\lim_{x \\to }",
}

TEMPLATES: Final[dict[str, str]] = {
    "Fraction": "\\frac{}{}",
    "Power": "^{}",
    "Subscript": "_{}",
    "Integral": "\\int_{}^{} \\, dx",
    "Matrix 2×2": "\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}",
}


def _symbol_buttons(
    symbols: dict[str, str],
    *,
    on_insert: Callable[[str], None],
    group_label: str,
) -> None:
    """Render a row of symbol buttons."""
    ui.label(group_label).classes("text-xs text-gray-500 font-semibold mt-2")
    with ui.row().classes("flex-wrap gap-1"):
        for display, latex in symbols.items():
            ui.button(display, on_click=lambda _, lx=latex: on_insert(lx)).props(
                "dense flat size=sm"
            ).classes("min-w-[2rem]")


def latex_assist_palette(
    *,
    level: AssistLevel,
    on_insert: Callable[[str], None],
) -> None:
    """Render the LaTeX assist palette at the given *level*."""
    if level == AssistLevel.EXPERT:
        return  # no palette at expert level

    with ui.expansion("LaTeX Assist", value=level == AssistLevel.FULL).classes("w-full"):
        _symbol_buttons(GREEK_SYMBOLS, on_insert=on_insert, group_label="Greek")
        _symbol_buttons(OPERATORS, on_insert=on_insert, group_label="Operators")
        _symbol_buttons(CALCULUS, on_insert=on_insert, group_label="Calculus")

        if level == AssistLevel.FULL:
            ui.label("Templates").classes("text-xs text-gray-500 font-semibold mt-2")
            with ui.row().classes("flex-wrap gap-1"):
                for name, latex in TEMPLATES.items():
                    ui.button(name, on_click=lambda _, lx=latex: on_insert(lx)).props(
                        "outline dense size=sm"
                    )
            ui.label("Tip: Use \\frac{a}{b} for fractions, ^{n} for powers").classes(
                "text-xs text-gray-400 mt-2 italic"
            )
