"""Review card component — type-to-recall flashcard for spaced repetition.

Enforces the pedagogical principle that the student MUST type a recall
attempt before seeing the answer (generation effect / Piaget's Predict phase).

The component is purely declarative — it receives state via parameters
and delegates state transitions to the parent via callbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from sophia.gui.components.math_input import KATEX_HEAD_HTML, sanitize_latex
from sophia.gui.services.review_service import RATING_LABELS

if TYPE_CHECKING:
    from collections.abc import Callable


def _render_katex_content(text: str) -> None:
    """Render sanitized *text* with KaTeX support inside a ui.html block."""
    clean = sanitize_latex(text)
    escaped = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ui.html(f'<span class="katex-content">{escaped}</span>')


def review_card(
    *,
    front: str,
    back: str,
    on_submit_recall: Callable[[str], None],
    on_rate: Callable[[int], None],
    interval_previews: dict[int, str],
    show_back: bool = False,
    recall_text: str = "",
) -> None:
    """Render a review card with type-to-recall flow.

    When *show_back* is ``False``, a text area is shown for the student's
    recall attempt.  When ``True``, the recall text, correct answer, and
    rating buttons are displayed instead.
    """
    ui.add_head_html(KATEX_HEAD_HTML, shared=True)

    with ui.card().classes("w-full max-w-lg mx-auto p-6"):
        # -- Front (always visible) ------------------------------------------
        ui.label("Question").classes("text-xs text-gray-500 uppercase tracking-wide")
        _render_katex_content(front)

        if not show_back:
            _render_recall_input(on_submit_recall)
        else:
            _render_answer_section(
                back=back,
                recall_text=recall_text,
                on_rate=on_rate,
                interval_previews=interval_previews,
            )


def _render_recall_input(on_submit_recall: Callable[[str], None]) -> None:
    """Render the recall text area and submit button."""
    ui.separator().classes("my-4")
    textarea = ui.textarea(label="Type your recall attempt").classes("w-full")
    textarea.props("autofocus")

    def _submit() -> None:
        on_submit_recall(textarea.value or "")

    ui.button("Submit", on_click=_submit).classes("mt-2")


def _render_answer_section(
    *,
    back: str,
    recall_text: str,
    on_rate: Callable[[int], None],
    interval_previews: dict[int, str],
) -> None:
    """Render the answer comparison and rating buttons."""
    ui.separator().classes("my-4")

    # Student's recall attempt
    ui.label("Your recall:").classes(
        "text-xs text-gray-500 uppercase tracking-wide",
    )
    ui.label(recall_text).classes("text-sm italic")

    ui.separator().classes("my-4")

    # Correct answer
    ui.label("Answer").classes("text-xs text-gray-500 uppercase tracking-wide")
    _render_katex_content(back)

    # Rating buttons
    with ui.row().classes("mt-4 gap-2 justify-center w-full"):
        for rating, label in RATING_LABELS.items():
            preview = interval_previews.get(rating, "")
            button_text = f"{label} ({preview})" if preview else label
            ui.button(
                button_text,
                on_click=lambda _, r=rating: on_rate(r),
            ).props("outline dense")
