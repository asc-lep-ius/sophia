"""Backup tooling: URL handling, tool preflight, and argument construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scripts import pg_backup

if TYPE_CHECKING:
    from pathlib import Path


def test_async_driver_is_stripped_for_libpq_tools() -> None:
    """pg_dump speaks libpq and rejects SQLAlchemy's +asyncpg suffix."""
    assert (
        pg_backup.libpq_url("postgresql+asyncpg://sophia:pw@db:5432/sophia")
        == "postgresql://sophia:pw@db:5432/sophia"
    )


def test_plain_libpq_urls_pass_through_unchanged() -> None:
    assert (
        pg_backup.libpq_url("postgresql://sophia@db:5432/sophia")
        == "postgresql://sophia@db:5432/sophia"
    )


def test_database_name_is_read_from_the_url_path() -> None:
    assert pg_backup.database_name("postgresql://sophia@db:5432/sophia") == "sophia"


def test_scratch_database_replaces_only_the_database_name() -> None:
    swapped = pg_backup.with_database("postgresql://sophia:pw@db:5432/sophia", "sophia_test")

    assert swapped == "postgresql://sophia:pw@db:5432/sophia_test"


def test_restore_drill_targets_a_scratch_database_not_the_source() -> None:
    """The drill must never restore over live data."""
    source = pg_backup.database_name("postgresql://sophia@db:5432/sophia")

    assert pg_backup.SCRATCH_SUFFIX
    assert f"{source}{pg_backup.SCRATCH_SUFFIX}" != source


def test_missing_tools_are_reported_by_name() -> None:
    assert pg_backup.missing_tools("definitely-not-a-real-binary") == [
        "definitely-not-a-real-binary"
    ]


def test_present_tools_are_not_reported() -> None:
    assert pg_backup.missing_tools("python3") == []


def test_backup_without_pg_dump_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing client binary is an actionable message, not a traceback."""
    monkeypatch.setattr(pg_backup.shutil, "which", lambda _name: None)

    assert pg_backup.backup("postgresql+asyncpg://a@h/db", tmp_path / "out.dump") == 2


def test_restore_without_a_dump_file_fails_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pg_backup.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert pg_backup.restore_drill("postgresql+asyncpg://a@h/db", tmp_path / "absent.dump") == 2


def test_backup_requires_an_output_path() -> None:
    with pytest.raises(SystemExit):
        pg_backup.main(["backup"])


def test_restore_requires_an_input_path() -> None:
    with pytest.raises(SystemExit):
        pg_backup.main(["restore"])
