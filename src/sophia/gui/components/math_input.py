"""Math input — LaTeX text area with live KaTeX preview.

All user-provided text rendered via ``ui.html()`` is sanitized to prevent XSS.
Only LaTeX/KaTeX markup is allowed; HTML tags are stripped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

_HTML_TAG_RE = re.compile(r"<[^>]+>")

KATEX_HEAD_HTML = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/contrib/auto-render.min.js"></script>'
)


def sanitize_latex(text: str) -> str:
    """Strip HTML tags from *text*, preserving only plain text and LaTeX."""
    return _HTML_TAG_RE.sub("", text)


def _escape_for_html(text: str) -> str:
    """Escape text for safe inclusion in HTML (not as JS, just display)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def math_input(
    *,
    value: str = "",
    label: str = "LaTeX input",
    on_change: Callable[[str], None] | None = None,
) -> ui.textarea:
    """Render a LaTeX input area with a live KaTeX preview below it.

    Returns the ``ui.textarea`` element so callers can bind to its value.
    KaTeX CDN is loaded via ``ui.add_head_html`` (once per page) and the
    preview area uses plain escaped text — actual rendering happens
    client-side via KaTeX's auto-render.
    """
    ui.add_head_html(KATEX_HEAD_HTML, shared=True)
    textarea = ui.textarea(label=label, value=value).classes("w-full font-mono")
    textarea.props('aria-label="LaTeX math input"')
    preview = ui.html("").classes("p-2 border rounded min-h-[2rem]")
    preview.props('aria-label="LaTeX preview" role="region"')

    def _update(e: object) -> None:
        raw = textarea.value or ""
        clean = sanitize_latex(raw)
        preview.content = _escape_for_html(clean)
        if on_change is not None:
            on_change(clean)

    textarea.on("change", _update)
    return textarea
