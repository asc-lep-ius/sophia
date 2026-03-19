"""LLM-based topic extraction adapter — extracts academic topic labels from text.

Supports GitHub Models, Gemini, Groq, and Ollama providers via the same
``HermesLLMConfig`` used by Hermes.  Optional dependencies are imported lazily;
a clear ``TopicExtractionError`` is raised if the required library is missing.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import TopicExtractionError

_INJECTION_LINE_RE = re.compile(
    r"^\s*(system\s*:|assistant\s*:|ignore\s+previous|disregard|forget\b)",
    re.IGNORECASE,
)
_MALICIOUS_FENCE_RE = re.compile(
    r"```(?:system|prompt)\b.*?```",
    re.DOTALL | re.IGNORECASE,
)

if TYPE_CHECKING:
    from sophia.domain.models import HermesLLMConfig

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are an academic topic extractor. Given a passage of lecture or course content, "
    "extract 5-15 distinct academic topic labels that represent the key concepts discussed. "
    "Return ONLY a numbered list of topic labels, one per line. "
    "Each topic should be a concise noun phrase (1-5 words). "
    "Always respond in the same language as the lecture content — "
    "if the content is in German, all topic labels must be in German. "
    "Do NOT include student names, IDs, or any personal information."
)

_OLLAMA_BASE_URL = "http://localhost:11434/v1"
_GITHUB_BASE_URL = "https://models.github.ai/inference"

_QUESTION_SYSTEM_PROMPT = (
    "You are a university-level practice question generator. "
    "Generate questions that test conceptual understanding, not surface recognition. "
    "Do NOT include student names, IDs, or any personal information."
)

_QUESTION_USER_TEMPLATE = (
    "Topic: {topic}\n\n"
    "Relevant lecture content:\n{lecture_context}\n\n"
    "Generate ONE practice question that:\n"
    "1. Tests understanding of the topic based on the lecture content above\n"
    "2. Requires the student to APPLY the concept, not just recognize key words\n"
    "3. Is appropriate for a university-level course\n\n"
    "Return ONLY the question text, nothing else."
)

_QUESTION_TEMPLATES: dict[str, str] = {
    "cued": (
        "Topic: {topic}\n\n"
        "Relevant lecture content:\n{lecture_context}\n\n"
        "Generate ONE retrieval-cue question that:\n"
        "1. Provides a partial statement or hint about the topic\n"
        "2. Asks the student to complete, identify, or match the concept\n"
        "3. Is appropriate for a student who is still building familiarity\n\n"
        "Return ONLY the question text, nothing else."
    ),
    "explain": _QUESTION_USER_TEMPLATE,
    "transfer": (
        "Topic: {topic}\n\n"
        "Relevant lecture content:\n{lecture_context}\n\n"
        "Generate ONE transfer/application question that:\n"
        "1. Presents a novel scenario not directly covered in the lecture\n"
        "2. Requires applying the concept to a new context or teaching it to someone\n"
        "3. Challenges a student who already understands the basics\n\n"
        "Return ONLY the question text, nothing else."
    ),
}


def _sanitize_user_content(text: str) -> str:
    """Strip patterns resembling LLM prompt injection from user-supplied text."""
    # Remove malicious code fences (```system, ```prompt)
    text = _MALICIOUS_FENCE_RE.sub("", text)
    # Remove lines that look like role overrides or instruction overrides
    lines = text.splitlines(keepends=True)
    return "".join(line for line in lines if not _INJECTION_LINE_RE.match(line))


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
    text = _sanitize_user_content(text)
    course_context = _sanitize_user_content(course_context)
    parts: list[str] = []
    if course_context:
        parts.append(f"Course: {course_context}\n")
    parts.append(f"Content:\n{text}")
    return "\n".join(parts)


class LLMTopicExtractor:
    """Extracts academic topics from text using an LLM provider."""

    def __init__(self, config: HermesLLMConfig) -> None:
        self._config = config

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Route LLM call to the configured provider."""
        from sophia.domain.models import LLMProvider

        try:
            if self._config.provider == LLMProvider.GEMINI:
                raw = await self._call_gemini(user_prompt, system_prompt=system_prompt)
            elif self._config.provider == LLMProvider.GROQ:
                raw = await self._call_groq(user_prompt, system_prompt=system_prompt)
            elif self._config.provider == LLMProvider.OLLAMA:
                raw = await self._call_openai(
                    user_prompt,
                    base_url=_OLLAMA_BASE_URL,
                    api_key="ollama",
                    system_prompt=system_prompt,
                )
            else:
                api_key = os.environ.get(self._config.api_key_env, "")
                raw = await self._call_openai(
                    user_prompt,
                    base_url=_GITHUB_BASE_URL,
                    api_key=api_key,
                    system_prompt=system_prompt,
                )
        except TopicExtractionError:
            raise
        except Exception as exc:
            raise TopicExtractionError(str(exc)) from exc
        return raw

    async def extract_topics(self, text: str, course_context: str = "") -> list[str]:
        """Extract topic labels from the given text via LLM.

        Returns a deduplicated, normalized list of topic strings.
        Raises ``TopicExtractionError`` on any failure.
        """
        user_prompt = _build_user_prompt(text, course_context)
        log.debug(
            "topic_extraction_request",
            provider=self._config.provider,
            model=self._config.model,
            text_len=len(text),
        )

        raw = await self._call_llm(_SYSTEM_PROMPT, user_prompt)
        topics = _parse_topics(raw)
        log.debug("topic_extraction_response", topic_count=len(topics), topics=topics)
        return topics

    async def generate_question(
        self, topic: str, lecture_context: str, difficulty: str = "explain"
    ) -> str:
        """Generate a practice question grounded in lecture content."""
        topic = _sanitize_user_content(topic)
        lecture_context = _sanitize_user_content(lecture_context)
        template = _QUESTION_TEMPLATES.get(difficulty, _QUESTION_TEMPLATES["explain"])
        user_prompt = template.format(topic=topic, lecture_context=lecture_context)
        raw = await self._call_llm(_QUESTION_SYSTEM_PROMPT, user_prompt)
        return raw.strip()

    async def _call_openai(
        self, user_prompt: str, *, base_url: str, api_key: str, system_prompt: str = _SYSTEM_PROMPT
    ) -> str:
        """Call an OpenAI-compatible API (GitHub Models or Ollama)."""
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError(
                "openai not installed — run: uv pip install openai"
            ) from None

        client: Any = AsyncOpenAI(base_url=base_url, api_key=api_key)  # pyright: ignore[reportUnknownVariableType]
        response: Any = await client.chat.completions.create(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    async def _call_gemini(self, user_prompt: str, *, system_prompt: str = _SYSTEM_PROMPT) -> str:
        """Call the Google Gemini API."""
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError(
                "google-genai not installed — run: uv pip install google-genai"
            ) from None

        api_key = os.environ.get(self._config.api_key_env, "")
        client: Any = genai.Client(api_key=api_key)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        response: Any = await client.aio.models.generate_content(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            model=self._config.model,
            contents=f"{system_prompt}\n\n{user_prompt}",
        )
        return response.text or ""  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    async def _call_groq(self, user_prompt: str, *, system_prompt: str = _SYSTEM_PROMPT) -> str:
        """Call the Groq API."""
        try:
            from groq import AsyncGroq  # type: ignore[import-not-found]
        except ImportError:
            raise TopicExtractionError("groq not installed — run: uv pip install groq") from None

        api_key = os.environ.get(self._config.api_key_env, "")
        client: Any = AsyncGroq(api_key=api_key)  # pyright: ignore[reportUnknownVariableType]
        response: Any = await client.chat.completions.create(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
