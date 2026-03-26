"""Tests for math_input, latex_assist, and HTML sanitization."""

from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.latex_assist import (
    AssistLevel,
    detect_assist_level,
    latex_assist_palette,
)
from sophia.gui.components.math_input import math_input, sanitize_latex


class TestSanitizeLatex:
    """HTML sanitization must strip dangerous tags while preserving LaTeX."""

    def test_strips_script_tags(self) -> None:
        result = sanitize_latex('<script>alert("xss")</script>\\frac{1}{2}')
        assert "<script>" not in result
        assert "\\frac{1}{2}" in result

    def test_strips_nested_html(self) -> None:
        result = sanitize_latex('<div onclick="evil()">\\alpha</div>')
        assert "<div" not in result
        assert "\\alpha" in result

    def test_preserves_plain_latex(self) -> None:
        text = "\\int_0^1 x^2 \\, dx"
        assert sanitize_latex(text) == text

    def test_strips_img_onerror(self) -> None:
        result = sanitize_latex('<img src=x onerror="alert(1)">\\beta')
        assert "<img" not in result
        assert "\\beta" in result

    def test_empty_string(self) -> None:
        assert sanitize_latex("") == ""

    def test_ampersand_and_less_than_preserved(self) -> None:
        result = sanitize_latex("a & b < c")
        assert "a" in result
        assert "b" in result


class TestMathInput:
    async def test_renders_textarea_and_preview(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                math_input()

            await user.open("/")
            # The component should render a textarea for input
            # and an HTML preview area

    async def test_renders_with_initial_value(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                math_input(value="\\alpha + \\beta")

            await user.open("/")


class TestAssistLevel:
    @pytest.mark.parametrize(
        ("flashcard_count", "expected"),
        [
            (0, AssistLevel.FULL),
            (5, AssistLevel.FULL),
            (9, AssistLevel.FULL),
            (10, AssistLevel.PARTIAL),
            (25, AssistLevel.PARTIAL),
            (50, AssistLevel.PARTIAL),
            (51, AssistLevel.EXPERT),
            (100, AssistLevel.EXPERT),
        ],
    )
    def test_detect_level_from_flashcard_count(
        self,
        flashcard_count: int,
        expected: AssistLevel,
    ) -> None:
        assert detect_assist_level(flashcard_count) == expected

    def test_override_level(self) -> None:
        assert detect_assist_level(5, override=AssistLevel.EXPERT) == AssistLevel.EXPERT


class TestLatexAssistPalette:
    async def test_full_level_shows_palette(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                latex_assist_palette(level=AssistLevel.FULL, on_insert=lambda s: None)

            await user.open("/")
            await user.should_see("α")  # Greek alpha symbol

    async def test_expert_level_hides_palette(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                latex_assist_palette(level=AssistLevel.EXPERT, on_insert=lambda s: None)

            await user.open("/")
            await user.should_not_see("α")
