"""Tests for adaptive difficulty mapping and difficulty-aware question templates."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from sophia.domain.models import DifficultyLevel
from sophia.services.athena_confidence import get_topic_difficulty_level

# Ensure optional LLM modules are importable for mocking.
if "openai" not in sys.modules:
    _openai = ModuleType("openai")
    _openai.AsyncOpenAI = MagicMock  # type: ignore[attr-defined]
    sys.modules["openai"] = _openai

if "groq" not in sys.modules:
    _groq = ModuleType("groq")
    _groq.AsyncGroq = MagicMock  # type: ignore[attr-defined]
    sys.modules["groq"] = _groq

if "google" not in sys.modules:
    sys.modules["google"] = ModuleType("google")
if "google.genai" not in sys.modules:
    _genai = ModuleType("google.genai")
    _genai.Client = MagicMock  # type: ignore[attr-defined]
    sys.modules["google.genai"] = _genai
    sys.modules["google"].genai = _genai  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Difficulty level mapping
# ---------------------------------------------------------------------------


class TestDifficultyLevelMapping:
    def test_difficulty_level_low(self) -> None:
        assert get_topic_difficulty_level(0.2) == DifficultyLevel.CUED

    def test_difficulty_level_medium(self) -> None:
        assert get_topic_difficulty_level(0.5) == DifficultyLevel.EXPLAIN

    def test_difficulty_level_high(self) -> None:
        assert get_topic_difficulty_level(0.9) == DifficultyLevel.TRANSFER

    def test_difficulty_level_none(self) -> None:
        assert get_topic_difficulty_level(None) == DifficultyLevel.EXPLAIN

    def test_difficulty_level_boundary_low(self) -> None:
        """Score 0.4 is NOT cued — boundary is exclusive (<0.4)."""
        assert get_topic_difficulty_level(0.4) == DifficultyLevel.EXPLAIN

    def test_difficulty_level_boundary_high(self) -> None:
        """Score 0.7 is NOT transfer — boundary is exclusive (>0.7)."""
        assert get_topic_difficulty_level(0.7) == DifficultyLevel.EXPLAIN


# ---------------------------------------------------------------------------
# Question templates
# ---------------------------------------------------------------------------


class TestQuestionTemplates:
    def test_question_template_cued_has_hint(self) -> None:
        from sophia.adapters.topic_extractor import _QUESTION_TEMPLATES

        template = _QUESTION_TEMPLATES["cued"]
        assert "hint" in template.lower() or "partial" in template.lower()

    def test_question_template_transfer_has_novel(self) -> None:
        from sophia.adapters.topic_extractor import _QUESTION_TEMPLATES

        template = _QUESTION_TEMPLATES["transfer"]
        assert "novel" in template.lower()

    def test_question_templates_all_have_topic_placeholder(self) -> None:
        from sophia.adapters.topic_extractor import _QUESTION_TEMPLATES

        for level, template in _QUESTION_TEMPLATES.items():
            assert "{topic}" in template, f"Template '{level}' missing {{topic}} placeholder"

    @pytest.mark.asyncio
    async def test_generate_question_default_difficulty(self) -> None:
        """Default difficulty='explain' uses the explain template."""
        from sophia.adapters.topic_extractor import LLMTopicExtractor
        from sophia.domain.models import HermesLLMConfig, LLMProvider

        config = HermesLLMConfig(
            provider=LLMProvider.GITHUB, model="openai/gpt-4o", api_key_env="GITHUB_TOKEN"
        )
        extractor = LLMTopicExtractor(config)

        captured_prompts: list[str] = []

        async def mock_call_llm(_self: object, system: str, user: str) -> str:
            captured_prompts.append(user)
            return "What is X?"

        extractor._call_llm = mock_call_llm.__get__(extractor)  # type: ignore[attr-defined]

        result = await extractor.generate_question("Algebra", "Some context")
        assert result == "What is X?"
        # Default should use explain template
        assert "APPLY the concept" in captured_prompts[0]
