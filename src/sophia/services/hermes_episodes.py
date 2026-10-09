"""The episodes a module has, whichever table knows about them.

``lecture_downloads`` was the episode catalogue for as long as every
transcript came from a download. A transcript read from the player's
captions (#156) has no download row, so an episode may now be known to
either table or to both, and a reader that lists a module's episodes goes
through here rather than through ``lecture_downloads`` alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from sophia.infra.schema import lecture_downloads, transcriptions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement, Select, Subquery
    from sqlalchemy.sql import Join


def episodes_from() -> Join:
    """Both tables, joined so an episode in only one of them still appears."""
    return lecture_downloads.join(
        transcriptions,
        lecture_downloads.c.episode_id == transcriptions.c.episode_id,
        full=True,
    )


def episode_id() -> ColumnElement[str]:
    return func.coalesce(lecture_downloads.c.episode_id, transcriptions.c.episode_id)


def episode_module_id() -> ColumnElement[int]:
    return func.coalesce(lecture_downloads.c.module_id, transcriptions.c.module_id)


def episode_title() -> ColumnElement[str]:
    """The download row's title where there is one; the transcript's own otherwise."""
    return func.coalesce(
        lecture_downloads.c.title,
        func.nullif(transcriptions.c.title, ""),
        "",
    )


def module_episode_ids_query(module_id: int) -> Select[tuple[str]]:
    return (
        select(episode_id().label("episode_id"))
        .select_from(episodes_from())
        .where(episode_module_id() == module_id)
    )


def module_episode_titles_query(module_id: int) -> Select[tuple[str, str]]:
    return (
        select(episode_id().label("episode_id"), episode_title().label("title"))
        .select_from(episodes_from())
        .where(episode_module_id() == module_id)
    )


def episode_titles_query(episode_ids: Sequence[str]) -> Select[tuple[str, str]]:
    return (
        select(episode_id().label("episode_id"), episode_title().label("title"))
        .select_from(episodes_from())
        .where(episode_id().in_(episode_ids))
    )


def episode_states() -> Subquery:
    """One row per episode: its id, its module, and the state of each stage it has.

    Aggregations group by the module through this rather than through the
    join directly, because a Postgres GROUP BY on the coalesced module id
    cannot also reference either table's own column in a correlated subquery.
    """
    return (
        select(
            episode_id().label("episode_id"),
            episode_module_id().label("module_id"),
            lecture_downloads.c.status.label("download_status"),
            transcriptions.c.status.label("transcription_status"),
        )
        .select_from(episodes_from())
        .subquery("episodes")
    )
