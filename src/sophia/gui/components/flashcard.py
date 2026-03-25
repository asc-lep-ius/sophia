"""Flashcard component — front/back card with KaTeX rendering and reveal."""

from __future__ import annotations

from nicegui import ui

from sophia.gui.components.math_input import KATEX_HEAD_HTML, sanitize_latex


def _render_katex_content(text: str) -> None:
    """Render sanitized *text* with KaTeX support inside a ui.html block."""
    clean = sanitize_latex(text)
    escaped = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ui.html(f'<span class="katex-content">{escaped}</span>')


def flashcard(
    *,
    front: str,
    back: str,
) -> None:
    """Render a flashcard with *front* visible and *back* hidden until reveal.

    The reveal is triggered by an explicit button click.
    Both sides support KaTeX rendering with HTML sanitization.
    """
    ui.add_head_html(KATEX_HEAD_HTML, shared=True)

    with ui.card().classes("w-full max-w-lg mx-auto p-6"):
        ui.label("Question").classes("text-xs text-gray-500 uppercase tracking-wide")
        _render_katex_content(front)

        back_container = ui.column().classes("w-full mt-4")
        back_container.visible = False

        with back_container:
            ui.separator()
            ui.label("Answer").classes("text-xs text-gray-500 uppercase tracking-wide mt-2")
            _render_katex_content(back)

        def _reveal() -> None:
            back_container.visible = True
            reveal_btn.visible = False

        reveal_btn = ui.button("Show Answer", on_click=_reveal).classes("mt-4 mx-auto")
