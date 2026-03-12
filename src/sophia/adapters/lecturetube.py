"""Async Opencast adapter — TUWEL Moodle Opencast module scraper.

Discovers lecture recordings from enrolled TUWEL courses by scraping
the Moodle Opencast plugin pages. Implements LectureProvider protocol.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

import httpx
import structlog
from bs4 import BeautifulSoup

from sophia.domain.errors import AuthError, LectureTubeError
from sophia.domain.models import Lecture, LectureTrack

log = structlog.get_logger()

_EPISODE_DATA_RE = re.compile(r"window\.episode\s*=\s*({.*?})\s*;", re.DOTALL)


def _parse_paella_tracks(data: dict[str, Any]) -> list[LectureTrack]:
    """Extract tracks from Paella player manifest's ``streams`` block."""
    tracks: list[LectureTrack] = []
    for stream in data.get("streams", []):
        content = stream.get("content", "")
        sources = stream.get("sources", {})
        for fmt, raw_items in sources.items():
            items_list = cast(
                "list[dict[str, Any]]",
                raw_items if isinstance(raw_items, list) else [raw_items],
            )
            for item in items_list:
                res = cast("dict[str, Any]", item.get("res", {}))
                w: int = res.get("w", 0)
                h: int = res.get("h", 0)
                resolution = f"{w}x{h}" if w and h else ""
                tracks.append(
                    LectureTrack(
                        flavor=f"{content}/{fmt}",
                        url=str(item.get("src", "")),
                        mimetype=str(item.get("mimetype", "")),
                        resolution=resolution,
                    )
                )
    return tracks


class OpencastAdapter:
    """Async TUWEL Opencast adapter — scrapes Moodle Opencast module pages.

    Satisfies: LectureProvider protocol.
    """

    def __init__(self, http: httpx.AsyncClient, host: str) -> None:
        self._http = http
        self._host = host.rstrip("/")

    async def _scrape(self, path: str, params: dict[str, str] | None = None) -> str:
        """Fetch a TUWEL page and return raw HTML. Detects auth redirects."""
        url = f"{self._host}{path}"
        log.debug("opencast.scrape", url=url, params=params)
        response = await self._http.get(
            url,
            params=params or {},
        )
        if "login" in str(response.url) and response.status_code in (200, 302):
            raise AuthError("Session expired — log in again with: sophia auth login")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LectureTubeError(f"HTTP {exc.response.status_code} from TUWEL Opencast") from exc
        return response.text

    async def get_series_episodes(self, module_id: int) -> list[Lecture]:
        """Scrape all episode links from an Opencast series module page."""
        html = await self._scrape("/mod/opencast/view.php", {"id": str(module_id)})
        soup = BeautifulSoup(html, "lxml")

        title_el = soup.select_one("h2") or soup.select_one(".page-header-headings h1")
        series_title = title_el.get_text(strip=True) if title_el else ""

        episodes: list[Lecture] = []
        for link in soup.select("a[href*='view.php'][href*='&e=']"):
            href = str(link.get("href", ""))
            ep_match = re.search(r"[&?]e=([0-9a-f-]{36})", href)
            if not ep_match:
                continue
            episode_id = ep_match.group(1)

            ep_title = link.get_text(strip=True)
            if not ep_title:
                img = link.select_one("img")
                ep_title = str(img.get("alt", "")) if img else ""

            episodes.append(
                Lecture(
                    episode_id=episode_id,
                    title=ep_title or episode_id,
                    series_id="",
                    series_title=series_title,
                )
            )

        return episodes

    async def get_episode_detail(self, module_id: int, episode_id: str) -> Lecture | None:
        """Scrape full episode metadata + track URLs from the player page."""
        html = await self._scrape("/mod/opencast/view.php", {"id": str(module_id), "e": episode_id})

        match = _EPISODE_DATA_RE.search(html)
        if not match:
            log.warning("opencast.no_episode_data", module_id=module_id, episode_id=episode_id)
            return None

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            log.warning("opencast.invalid_episode_json", module_id=module_id, episode_id=episode_id)
            return None

        metadata = data.get("metadata", {})
        return Lecture(
            episode_id=episode_id,
            title=str(metadata.get("title", "")),
            series_id=str(metadata.get("series", "")),
            series_title=str(metadata.get("seriestitle", "")),
            duration_ms=int(metadata.get("duration", 0)) * 1000,
            created=str(metadata.get("startDate", "")),
            creator=str(metadata.get("presenter", "")),
            tracks=_parse_paella_tracks(data),
        )
