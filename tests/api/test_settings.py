"""Settings API route tests."""

from __future__ import annotations

from typing import override

from sophia.api.sessions import RedisSessionStore, SessionRecord

from ._session_helpers import FakeRedis, build_harness, csrf_headers, login


def test_settings_requires_authentication() -> None:
    harness = build_harness()

    get_response = harness.client.get("/api/settings")
    patch_response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark"},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert get_response.status_code == 401
    assert patch_response.status_code == 401
    assert get_response.json() == {"detail": {"code": "auth.failed", "params": {}}}
    assert patch_response.json() == {"detail": {"code": "auth.failed", "params": {}}}


def test_authenticated_get_returns_session_settings() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.get("/api/settings")

    assert response.status_code == 200
    assert response.json() == {
        "theme": "system",
        "locale": "en",
        "selected_learning_path_id": "course-1",
    }


def test_patch_requires_csrf_headers() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.patch("/api/settings", json={"theme": "dark"})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "http.failed", "params": {}}}


def test_patch_persists_settings_in_session_record() -> None:
    harness = build_harness()
    login(harness)

    patch_response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark", "locale": "de", "selected_learning_path_id": "course-2"},
        headers=csrf_headers(harness),
    )
    get_response = harness.client.get("/api/settings")

    assert patch_response.status_code == 200
    assert patch_response.json() == {
        "theme": "dark",
        "locale": "de",
        "selected_learning_path_id": "course-2",
    }
    assert get_response.status_code == 200
    assert get_response.json() == patch_response.json()


def test_patch_can_clear_selected_course() -> None:
    harness = build_harness()
    login(harness)

    response = harness.client.patch(
        "/api/settings",
        json={"selected_learning_path_id": None},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    assert response.json()["selected_learning_path_id"] is None


def test_stale_route_save_returns_unauthorized_without_resurrecting_session() -> None:
    redis = FakeRedis()
    expiring_store = ExpiringSaveStore(
        redis=redis,
        ttl_seconds=600,
    )
    harness = build_harness(store=expiring_store, redis=redis)
    login(harness)

    response = harness.client.patch(
        "/api/settings",
        json={"theme": "dark"},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "auth.failed", "params": {}}}
    assert harness.redis.values == {}


class ExpiringSaveStore(RedisSessionStore):
    @override
    async def save(self, record: SessionRecord) -> bool:
        await self.delete(record.session_id)
        return await RedisSessionStore.save(self, record)
