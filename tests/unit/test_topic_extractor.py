"""Tests for the LLM-based topic extraction adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import HermesLLMConfig, LLMProvider


def _make_config(
    provider: LLMProvider = LLMProvider.GITHUB,
    model: str = "openai/gpt-4o",
    api_key_env: str = "GITHUB_TOKEN",
) -> HermesLLMConfig:
    return HermesLLMConfig(provider=provider, model=model, api_key_env=api_key_env)


class TestLLMTopicExtractor:
    """Tests for the LLMTopicExtractor adapter."""

    def test_import(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        extractor = LLMTopicExtractor(_make_config())
        assert extractor is not None

    @pytest.mark.asyncio
    async def test_extract_topics_github(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[
            0
        ].message.content = "1. Linear Algebra\n2. Matrix Operations\n3. Vector Spaces"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            extractor = LLMTopicExtractor(_make_config())
            topics = await extractor.extract_topics("Lecture about linear algebra and matrices")

        assert "Linear Algebra" in topics
        assert "Matrix Operations" in topics
        assert "Vector Spaces" in topics

    @pytest.mark.asyncio
    async def test_extract_topics_deduplicates(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[
            0
        ].message.content = "1. Linear Algebra\n2. linear algebra\n3. Vector Spaces"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            extractor = LLMTopicExtractor(_make_config())
            topics = await extractor.extract_topics("Some text")

        # Should have deduplicated case-insensitively, keeping first occurrence
        lower_topics = [t.lower() for t in topics]
        assert lower_topics.count("linear algebra") == 1
        assert "Vector Spaces" in topics

    @pytest.mark.asyncio
    async def test_extract_topics_with_context(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "1. Quantum Physics"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            extractor = LLMTopicExtractor(_make_config())
            topics = await extractor.extract_topics(
                "Wave functions and superposition", course_context="Physics 101"
            )

        assert "Quantum Physics" in topics
        # Verify course_context was passed in the prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "Physics 101" in user_msg["content"]

    @pytest.mark.asyncio
    async def test_extract_topics_api_error_raises(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            extractor = LLMTopicExtractor(_make_config())
            with pytest.raises(TopicExtractionError, match="API down"):
                await extractor.extract_topics("Some text")

    @pytest.mark.asyncio
    async def test_extract_topics_empty_response(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client):
            extractor = LLMTopicExtractor(_make_config())
            topics = await extractor.extract_topics("Some text")

        assert topics == []

    @pytest.mark.asyncio
    async def test_gemini_provider(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        config = _make_config(
            provider=LLMProvider.GEMINI,
            model="gemini-2.0-flash",
            api_key_env="SOPHIA_GEMINI_API_KEY",
        )

        mock_response = MagicMock()
        mock_response.text = "1. Neural Networks\n2. Backpropagation"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch("google.genai.Client", return_value=mock_client):
            extractor = LLMTopicExtractor(config)
            topics = await extractor.extract_topics("Deep learning lecture")

        assert "Neural Networks" in topics
        assert "Backpropagation" in topics

    @pytest.mark.asyncio
    async def test_groq_provider(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        config = _make_config(
            provider=LLMProvider.GROQ,
            model="llama-3.3-70b-versatile",
            api_key_env="SOPHIA_GROQ_API_KEY",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "1. Data Structures"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("groq.AsyncGroq", return_value=mock_client):
            extractor = LLMTopicExtractor(config)
            topics = await extractor.extract_topics("Trees and graphs")

        assert "Data Structures" in topics

    @pytest.mark.asyncio
    async def test_ollama_provider_uses_openai_with_custom_base(self) -> None:
        from sophia.adapters.topic_extractor import LLMTopicExtractor

        config = _make_config(
            provider=LLMProvider.OLLAMA,
            model="llama3.2",
            api_key_env="",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "1. Algorithms"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            extractor = LLMTopicExtractor(config)
            topics = await extractor.extract_topics("Sorting algorithms")

        assert "Algorithms" in topics
        # Verify it used the Ollama base URL
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert "localhost:11434" in call_kwargs["base_url"]


class TestParseTopics:
    """Tests for _parse_topics helper."""

    def test_numbered_list(self) -> None:
        from sophia.adapters.topic_extractor import _parse_topics

        text = "1. Linear Algebra\n2. Calculus\n3. Statistics"
        assert _parse_topics(text) == ["Linear Algebra", "Calculus", "Statistics"]

    def test_bullet_list(self) -> None:
        from sophia.adapters.topic_extractor import _parse_topics

        text = "- Linear Algebra\n- Calculus\n- Statistics"
        assert _parse_topics(text) == ["Linear Algebra", "Calculus", "Statistics"]

    def test_strips_whitespace(self) -> None:
        from sophia.adapters.topic_extractor import _parse_topics

        text = "  1.  Linear Algebra  \n  2. Calculus  "
        assert _parse_topics(text) == ["Linear Algebra", "Calculus"]

    def test_empty_input(self) -> None:
        from sophia.adapters.topic_extractor import _parse_topics

        assert _parse_topics("") == []

    def test_deduplicates_case_insensitive(self) -> None:
        from sophia.adapters.topic_extractor import _parse_topics

        text = "1. Linear Algebra\n2. linear algebra\n3. Calculus"
        result = _parse_topics(text)
        assert len(result) == 2
        assert result[0] == "Linear Algebra"
        assert result[1] == "Calculus"
