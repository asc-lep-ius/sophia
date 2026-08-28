"""Resolved content language for a learning path.

Exists so the study surface can ask what language to study in rather than
guessing from its own locale, which is precisely the misuse this phase guards
against.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, status

from sophia.api.deps import get_app_container, get_settings, require_learning_path_scope
from sophia.api.schemas.content import (
    ContentKind,
    ContentLanguage,
    ContentLanguageOrigin,
    ContentLanguageResponse,
    ContentTranslation,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.domain.learning import ContentLanguage as DomainContentLanguage
from sophia.services.content_language import get_translations, resolve_content_language

router = APIRouter(tags=["content-language"])

LearningPathIdPath = Annotated[int, Path(gt=0)]
LanguageOverrideQuery = Annotated[ContentLanguage | None, Query(alias="lang")]


@router.get(
    "/learning-paths/{learning_path_id}/content-language",
    response_model=ContentLanguageResponse,
    operation_id="getContentLanguage",
    responses={status.HTTP_403_FORBIDDEN: {"model": ErrorEnvelope}},
)
async def get_content_language(
    learning_path_id: LearningPathIdPath,
    request: Request,
    lang: LanguageOverrideQuery = None,
) -> ContentLanguageResponse:
    await require_learning_path_scope(request, learning_path_id)
    db = get_app_container(request).db
    settings = get_settings(request)

    resolved = await resolve_content_language(
        db,
        learning_path_id,
        override=None if lang is None else DomainContentLanguage(lang.value),
        default_language=DomainContentLanguage(settings.default_content_language),
    )
    translations = await get_translations(db, learning_path_id)
    return ContentLanguageResponse(
        learning_path_id=learning_path_id,
        content_language=ContentLanguage(resolved.language.value),
        resolved_from=ContentLanguageOrigin(resolved.resolved_from),
        available_translations=[
            ContentTranslation(
                content_kind=ContentKind(translation.content_kind.value),
                content_id=translation.content_id,
                language=ContentLanguage(translation.language.value),
                translated_at=translation.translated_at,
            )
            for translation in translations
        ],
    )
