"""Async LectureTube adapter — Opencast Search API client.

Fetches series and episode data from TU Wien's LectureTube platform
(Opencast-based). Implements LectureProvider protocol.
"""

from __future__ import annotations

from typing import Any, cast

import httpx
import structlog

from sophia.domain.errors import AuthError, LectureTubeError
from sophia.domain.models import Lecture, LectureSeries, LectureTrack

log = structlog.get_logger()


def _ensure_list(value: Any) -> list[dict[str, Any]]:
    """Normalize Opencast's single-object-or-array JSON quirk."""
    if isinstance(value, list):
        return value  # type: ignore[no-any-return]
    return [value]


def _parse_tracks(media: dict[str, Any]) -> list[LectureTrack]:
    """Extract tracks from a mediapackage's ``media`` block."""
    raw_tracks = media.get("track")
    if not raw_tracks:
        return []
    tracks: list[LectureTrack] = []
    for t in _ensure_list(raw_tracks):
        video: dict[str, str] = t.get("video") or {}
        tracks.append(
            LectureTrack(
                flavor=str(t.get("type", "")),
                url=str(t.get("url", "")),
                mimetype=str(t.get("mimetype", "")),
                resolution=str(video.get("resolution", "")),
            )
        )
    return tracks


def _parse_creator(creators: Any) -> str:
    """Extract creator string — can be a string or ``{"creator": "..."}``."""
    if not isinstance(creators, dict):
        return ""
    creators_dict = cast("dict[str, Any]", creators)
    raw: str | list[str] = creators_dict.get("creator", "")
    if isinstance(raw, list):
        return ", ".join(str(c) for c in raw)
    return str(raw)


class LectureTubeAdapter:
    """Async LectureTube adapter — Opencast Search API client.

    Satisfies: LectureProvider protocol.
    """

    def __init__(self, http: httpx.AsyncClient, host: str) -> None:
        self._http = http
        self._host = host.rstrip("/")

    async def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """GET a JSON endpoint, handling auth redirects and HTTP errors."""
        url = f"{self._host}{path}"
        log.debug("lecturetube.request", url=url, params=params)

        try:
            response = await self._http.get(url, params=params, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise LectureTubeError(f"LectureTube request failed: {path}") from exc

        # SSO redirect → not authenticated
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location", "")
            if "login" in location or "idp" in location:
                raise AuthError("Session expired — log in again with: sophia auth login")

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LectureTubeError(
                f"HTTP {exc.response.status_code} from LectureTube: {path}"
            ) from exc

        return response.json()  # type: ignore[no-any-return]

    async def search_series(self, query: str) -> list[LectureSeries]:
        """Search for lecture series matching *query*."""
        data = await self._get_json("/search/series.json", {"q": query, "limit": "20"})
        sr = data.get("search-results", {})
        if int(sr.get("total", 0)) == 0:
            return []

        results: list[LectureSeries] = []
        for item in _ensure_list(sr["result"]):
            mp = item.get("mediapackage", {})
            title = item.get("dcTitle") or mp.get("title", "")
            results.append(
                LectureSeries(
                    series_id=mp.get("id", item.get("id", "")),
                    title=title,
                )
            )
        return results

    async def get_episodes(self, series_id: str) -> list[Lecture]:
        """List episodes for a given series, newest first."""
        data = await self._get_json(
            "/search/episode.json",
            {"sid": series_id, "limit": "100", "sort": "created desc"},
        )
        sr = data.get("search-results", {})
        if int(sr.get("total", 0)) == 0:
            return []

        results: list[Lecture] = []
        for item in _ensure_list(sr["result"]):
            mp = item.get("mediapackage", {})
            results.append(
                Lecture(
                    episode_id=mp.get("id", item.get("id", "")),
                    title=mp.get("title", ""),
                    series_id=mp.get("series", ""),
                    series_title=mp.get("seriestitle", ""),
                    duration_ms=int(mp.get("duration", 0)),
                    created=mp.get("start", ""),
                    creator=_parse_creator(mp.get("creators")),
                    tracks=_parse_tracks(mp.get("media", {})),
                )
            )
        return results
