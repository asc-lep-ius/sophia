"""Content language fallback: exam language wins, UI locale never does."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest

from sophia.api.sessions import SessionTenant
from sophia.domain.learning import ContentLanguage, LearningPathSettings, StoredContentOrigin
from sophia.domain.models import Course
from sophia.infra.persistence import run_migrations
from sophia.services.content_language import (
    get_learning_path_settings,
    resolve_content_language,
    save_learning_path_settings,
    sync_learning_path_settings,
)

from ._session_helpers import ApiHarness, build_harness, login

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sophia.infra.di import AppContainer

LEARNING_PATH_ID = 12


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: aiosqlite.Connection


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys=ON")
    await run_migrations(connection)
    yield connection
    await connection.close()


def build_logged_in_harness(db: aiosqlite.Connection) -> ApiHarness:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=SessionTenant(
            org_id="tu-wien",
            learning_path_id=str(LEARNING_PATH_ID),
            cohort_id="cohort-a",
            role="student",
        ),
    )
    login(harness)
    return harness


async def store_exam_language(db: aiosqlite.Connection, language: ContentLanguage) -> None:
    await save_learning_path_settings(
        db,
        LearningPathSettings(
            course_id=LEARNING_PATH_ID,
            exam_language=language,
            content_origin=StoredContentOrigin.TUWEL,
        ),
    )


async def test_learning_path_exam_language_beats_the_ui_locale(db: aiosqlite.Connection) -> None:
    """The test session's UI locale is English; the exam is in German."""
    await store_exam_language(db, ContentLanguage.DE)
    harness = build_logged_in_harness(db)

    response = harness.client.get(f"/api/learning-paths/{LEARNING_PATH_ID}/content-language")

    assert response.status_code == 200
    assert response.json()["content_language"] == "de"
    assert response.json()["resolved_from"] == "learning_path"


async def test_explicit_lang_override_wins(db: aiosqlite.Connection) -> None:
    await store_exam_language(db, ContentLanguage.DE)
    harness = build_logged_in_harness(db)

    response = harness.client.get(
        f"/api/learning-paths/{LEARNING_PATH_ID}/content-language?lang=en"
    )

    assert response.json()["content_language"] == "en"
    assert response.json()["resolved_from"] == "override"


async def test_configured_default_applies_when_the_path_has_no_exam_language(
    db: aiosqlite.Connection,
) -> None:
    harness = build_logged_in_harness(db)

    response = harness.client.get(f"/api/learning-paths/{LEARNING_PATH_ID}/content-language")

    assert response.json()["content_language"] == "de"
    assert response.json()["resolved_from"] == "default"


async def test_unknown_language_override_is_rejected(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    response = harness.client.get(
        f"/api/learning-paths/{LEARNING_PATH_ID}/content-language?lang=fr"
    )

    assert response.status_code == 422


async def test_content_language_is_scoped_to_the_session(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    response = harness.client.get("/api/learning-paths/99/content-language")

    assert response.status_code == 403


async def test_translations_are_reserved_and_start_empty(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    response = harness.client.get(f"/api/learning-paths/{LEARNING_PATH_ID}/content-language")

    assert response.json()["available_translations"] == []


async def test_fallback_order_is_override_then_path_then_default(
    db: aiosqlite.Connection,
) -> None:
    await store_exam_language(db, ContentLanguage.EN)

    override = await resolve_content_language(
        db,
        LEARNING_PATH_ID,
        override=ContentLanguage.DE,
        default_language=ContentLanguage.DE,
    )
    from_path = await resolve_content_language(
        db,
        LEARNING_PATH_ID,
        override=None,
        default_language=ContentLanguage.DE,
    )
    from_default = await resolve_content_language(
        db,
        999,
        override=None,
        default_language=ContentLanguage.DE,
    )

    assert (override.language, override.resolved_from) == (ContentLanguage.DE, "override")
    assert (from_path.language, from_path.resolved_from) == (ContentLanguage.EN, "learning_path")
    assert (from_default.language, from_default.resolved_from) == (ContentLanguage.DE, "default")


async def test_sync_stores_the_language_the_upstream_source_reports(
    db: aiosqlite.Connection,
) -> None:
    stored = await sync_learning_path_settings(
        db,
        [
            Course(id=12, fullname="Analysis", shortname="AN", exam_language="de"),
            Course(id=13, fullname="Compilers", shortname="CO", exam_language="en"),
        ],
    )

    assert stored == 2
    settings = await get_learning_path_settings(db, 13)
    assert settings is not None
    assert settings.exam_language == ContentLanguage.EN
    assert settings.content_origin == StoredContentOrigin.TUWEL


async def test_sync_skips_paths_whose_language_is_unknown(db: aiosqlite.Connection) -> None:
    """An unstated upstream language must not be pinned to a guess."""
    stored = await sync_learning_path_settings(
        db,
        [Course(id=12, fullname="Analysis", shortname="AN", exam_language=None)],
    )

    assert stored == 0
    assert await get_learning_path_settings(db, 12) is None


async def test_sync_updates_a_language_that_changed_upstream(
    db: aiosqlite.Connection,
) -> None:
    await store_exam_language(db, ContentLanguage.DE)

    await sync_learning_path_settings(
        db,
        [Course(id=LEARNING_PATH_ID, fullname="Analysis", shortname="AN", exam_language="en")],
    )

    settings = await get_learning_path_settings(db, LEARNING_PATH_ID)
    assert settings is not None
    assert settings.exam_language == ContentLanguage.EN
