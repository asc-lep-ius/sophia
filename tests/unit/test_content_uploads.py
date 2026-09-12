"""Content-source upload boundary — validation, sniffing, and staging."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.domain.errors import ContentUploadRejected
from sophia.services.content_uploads import (
    STAGING_DIR_NAME,
    IngestionState,
    UploadRejection,
    accepted_extensions,
    format_for_filename,
    normalize_title,
    stage_upload,
)

if TYPE_CHECKING:
    from pathlib import Path

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00"


def chunk_reader(payload: bytes):  # noqa: ANN201 — returns a local async closure
    """Hand back ``payload`` the way an ``UploadFile.read`` would."""
    remaining = bytearray(payload)

    async def read(size: int) -> bytes:
        chunk = bytes(remaining[:size])
        del remaining[: len(chunk)]
        return chunk

    return read


def rejection_reason(error: ContentUploadRejected) -> str:
    return str(error.params["reason"])


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("  Graph   algorithms\n") == "Graph algorithms"


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("", UploadRejection.TITLE_REQUIRED),
        ("   ", UploadRejection.TITLE_REQUIRED),
        (None, UploadRejection.TITLE_REQUIRED),
        ("x" * 201, UploadRejection.TITLE_TOO_LONG),
    ],
)
def test_normalize_title_refuses_unusable_titles(
    title: str | None, reason: UploadRejection
) -> None:
    with pytest.raises(ContentUploadRejected) as excinfo:
        normalize_title(title)

    assert rejection_reason(excinfo.value) == reason.value


def test_format_for_filename_reads_only_the_extension() -> None:
    assert format_for_filename("../../etc/Lecture 1.PDF").media_type == "application/pdf"


@pytest.mark.parametrize(
    ("filename", "reason"),
    [
        (None, UploadRejection.FILE_REQUIRED),
        ("", UploadRejection.FILE_REQUIRED),
        ("payload.exe", UploadRejection.UNSUPPORTED_TYPE),
        ("no-extension", UploadRejection.UNSUPPORTED_TYPE),
    ],
)
def test_format_for_filename_refuses_types_outside_the_allowlist(
    filename: str | None,
    reason: UploadRejection,
) -> None:
    with pytest.raises(ContentUploadRejected) as excinfo:
        format_for_filename(filename)

    assert rejection_reason(excinfo.value) == reason.value


def test_accepted_extensions_names_every_supported_format() -> None:
    assert accepted_extensions().split() == [".pdf", ".epub", ".mp3", ".m4a", ".mp4", ".wav"]


@pytest.mark.asyncio
async def test_stage_upload_writes_the_payload_and_queues_it(tmp_path: Path) -> None:
    staged = await stage_upload(
        title=" Graph algorithms ",
        filename="lecture-01.pdf",
        read_chunk=chunk_reader(PDF_BYTES),
        data_dir=tmp_path,
        max_bytes=1024,
    )

    assert staged.title == "Graph algorithms"
    assert staged.media_type == "application/pdf"
    assert staged.byte_size == len(PDF_BYTES)
    assert staged.state is IngestionState.QUEUED
    assert staged.stored_path.parent == tmp_path / STAGING_DIR_NAME
    assert staged.stored_path.read_bytes() == PDF_BYTES


@pytest.mark.asyncio
async def test_stage_upload_sniffs_a_container_signature_past_offset_zero(
    tmp_path: Path,
) -> None:
    staged = await stage_upload(
        title="Recording",
        filename="lecture-01.mp4",
        read_chunk=chunk_reader(MP4_BYTES),
        data_dir=tmp_path,
        max_bytes=1024,
    )

    assert staged.media_type == "video/mp4"


@pytest.mark.asyncio
async def test_stage_upload_refuses_bytes_that_contradict_the_extension(tmp_path: Path) -> None:
    """The extension and the part header are both caller-controlled.

    An executable renamed to `.pdf` is the whole reason the sniff exists, so it
    has to be refused and the partial write has to be cleaned up behind it.
    """
    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Disguised",
            filename="lecture-01.pdf",
            read_chunk=chunk_reader(b"MZ\x90\x00executable payload"),
            data_dir=tmp_path,
            max_bytes=1024,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.CONTENT_MISMATCH.value
    assert list((tmp_path / STAGING_DIR_NAME).iterdir()) == []


@pytest.mark.asyncio
async def test_stage_upload_refuses_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Nothing",
            filename="lecture-01.pdf",
            read_chunk=chunk_reader(b""),
            data_dir=tmp_path,
            max_bytes=1024,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.EMPTY_FILE.value
    assert list((tmp_path / STAGING_DIR_NAME).iterdir()) == []


@pytest.mark.asyncio
async def test_stage_upload_stops_at_the_ceiling_rather_than_after_it(tmp_path: Path) -> None:
    """The ceiling is enforced while reading, not once the body has landed."""
    oversized = PDF_BYTES + b"0" * 4096

    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Too big",
            filename="lecture-01.pdf",
            read_chunk=chunk_reader(oversized),
            data_dir=tmp_path,
            max_bytes=64,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.TOO_LARGE.value
    assert excinfo.value.params["max_bytes"] == 64
    assert list((tmp_path / STAGING_DIR_NAME).iterdir()) == []
