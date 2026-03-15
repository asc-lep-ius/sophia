"""LLM-based topic extraction adapter — extracts academic topic labels from text.

Supports GitHub Models, Gemini, Groq, and Ollama providers via the same
``HermesLLMConfig`` used by Hermes.  Optional dependencies are imported lazily;
a clear ``TopicExtractionError`` is raised if the required library is missing.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import TopicExtractionError

if TYPE_CHECKING:
    from sophia.domain.models import HermesLLMConfig

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are an academic topic extractor. Given a passage of lecture or course content, "
    "extract 5-15 distinct academic topic labels that represent the key concepts discussed. "
    "Return ONLY a numbered list of topic labels, one per line. "
    "Each topic should be a concise noun phrase (1-5 words). "
    "Do NOT include student names, IDs, or any personal information."
)

_OLLAMA_BASE_URL = "http://localhost:11434/v1"
_GITHUB_BASE_URL = "https://models.github.ai/inference/v1"


def _parse_topics(text: str) -> list[str]:
    """Parse LLM response into a deduplicated list of topic strings."""
    if not text.strip():
        return []

    topics: list[str] = []
    seen_lower: set[str] = set()

    for line in text.strip().splitlines():
        # Strip numbering (1. / 1) / -) and whitespace
        cleaned = re.sub(r"^\s*(?:\d+[.)]\s*|[-*]\s*)", "", line).strip()
        if not cleaned:
            continue
        lower = cleaned.lower()
        if lower not in seen_lower:
            seen_lower.add(lower)
            topics.append(cleaned)

    return topics


def _build_user_prompt(text: str, course_context: str) -> str:
    """Build the user prompt, injecting course context if provided."""
    parts = []
    if course_context:
        parts.append(f"Course: {course_context}\n")
    parts.append(f"Content:\n{text}")
    return "\n".join(parts)


class LLMTopicExtractor:
    """Extracts academic topics from text using an LLM provider."""

    def __init__(self, config: HermesLLMConfig) -> None:
        self._config = config

    async def extract_topics(self, text: str, course_context: str = "") -> list[str]:
        """Extract topic labels from the given text via LLM.

        Returns a deduplicated, normalized list of topic strings.
        Raises ``TopicExtractionError`` on any failure.
        """
        from sophia.domain.models import LLMProvider

        user_prompt = _build_user_prompt(text, course_context)
        log.debug(
            "topic_extraction_request",
            provider=self._config.provider,
            model=self._config.model,
            text_len=len(text),
        )

        try:
            if self._config.provider == LLMProvider.GEMINI:
                raw = await self._call_gemini(user_prompt)
            elif self._config.provider == LLMProvider.GROQ:
                raw = await self._call_groq(user_prompt)
            elif self._config.provider == LLMProvider.OLLAMA:
                raw = await self._call_openai(
                    user_prompt, base_url=_OLLAMA_BASE_URL, api_key="ollama"
                )
            else:
                # GitHub Models (default) — OpenAI-compatible
                api_key = os.environ.get(self._config.api_key_env, "")
                raw = await self._call_openai(
                    user_prompt, base_url=_GITHUB_BASE_URL, api_key=api_key
                )
        except TopicExtractionError:
            raise
        except Exception as exc:
            raise TopicExtractionError(str(exc)) from exc

        topics = _parse_topics(raw)
        log.debug("topic_extraction_response", topic_count=len(topics), topics=topics)
        return topics

    async def _call_openai(self, user_prompt: str, *, base_url: str, api_key: str) -> str:
        """Call an OpenAI-compatible API (GitHub Models or Ollama)."""
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError(
                "openai not installed — run: uv pip install openai"
            ) from None

        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        response = await client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""

    async def _call_gemini(self, user_prompt: str) -> str:
        """Call the Google Gemini API."""
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError(
                "google-genai not installed — run: uv pip install google-genai"
            ) from None

        api_key = os.environ.get(self._config.api_key_env, "")
        client = genai.Client(api_key=api_key)
        response = await client.aio.models.generate_content(
            model=self._config.model,
            contents=f"{_SYSTEM_PROMPT}\n\n{user_prompt}",
        )
        return response.text or ""

    async def _call_groq(self, user_prompt: str) -> str:
        """Call the Groq API."""
        try:
            from groq import AsyncGroq  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError("groq not installed — run: uv pip install groq") from None

        api_key = os.environ.get(self._config.api_key_env, "")
        client = AsyncGroq(api_key=api_key)
        response = await client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
