"""Content language and translation transport schemas."""

from __future__ import annotations

from enum import StrEnum

from sophia.api.schemas.common import ApiModel


class ContentLanguage(StrEnum):
    """Language a piece of learning content is authored in.

    Deliberately separate from the UI locale: content follows the exam language
    of the learning path, never the language of the chrome around it.
    """

    DE = "de"
    EN = "en"


class ContentKind(StrEnum):
    """What kind of content a translation record describes."""

    FLASHCARD = "flashcard"
    QUESTION = "question"
    SUMMARY = "summary"


class ContentLanguageOrigin(StrEnum):
    """Which fallback rung decided the content language of a response."""

    OVERRIDE = "override"
    LEARNING_PATH = "learning_path"
    DEFAULT = "default"


class ContentTranslation(ApiModel):
    """A translated rendering of a content item.

    Reserved shape. Nothing writes these until the translation pipeline ships;
    the field exists so adding translations later is additive for clients.
    """

    content_kind: ContentKind
    content_id: str
    language: ContentLanguage
    translated_at: str


class ContentLanguageResponse(ApiModel):
    """The resolved content language for a learning path, and how it was chosen."""

    learning_path_id: int
    content_language: ContentLanguage
    resolved_from: ContentLanguageOrigin
    available_translations: list[ContentTranslation]
