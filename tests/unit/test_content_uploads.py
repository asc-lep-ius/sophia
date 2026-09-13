"""Content-source upload boundary — validation, sniffing, and staging."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.domain.errors import ContentUploadRejected
from sophia.services.content_uploads import (
    IngestionState,
    UploadRejection,
    accepted_extensions,
    format_for_filename,
    normalize_title,
    stage_upload,
    staging_dir,
)

if TYPE_CHECKING:
    from pathlib import Path

LEARNING_PATH_ID = "12"

PDF_BYTES = b"%PDF-1.7\n1 0 obj\n"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00"
# A ZIP local file header puts the name at offset 30; EPUB requires an
# uncompressed `mimetype` entry first, which puts its value at 38.
EPUB_BYTES = b"PK\x03\x04" + bytes(26) + b"mimetype" + b"application/epub+zip"
WAV_BYTES = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVEfmt "


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
        learning_path_id=LEARNING_PATH_ID,
        max_bytes=1024,
    )

    assert staged.title == "Graph algorithms"
    assert staged.media_type == "application/pdf"
    assert staged.byte_size == len(PDF_BYTES)
    assert staged.state is IngestionState.QUEUED
    assert staged.stored_path.parent == staging_dir(tmp_path, LEARNING_PATH_ID)
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
        learning_path_id=LEARNING_PATH_ID,
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
            learning_path_id=LEARNING_PATH_ID,
            max_bytes=1024,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.CONTENT_MISMATCH.value
    assert list(staging_dir(tmp_path, LEARNING_PATH_ID).iterdir()) == []


@pytest.mark.asyncio
async def test_stage_upload_refuses_an_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Nothing",
            filename="lecture-01.pdf",
            read_chunk=chunk_reader(b""),
            data_dir=tmp_path,
            learning_path_id=LEARNING_PATH_ID,
            max_bytes=1024,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.EMPTY_FILE.value
    assert list(staging_dir(tmp_path, LEARNING_PATH_ID).iterdir()) == []


@pytest.mark.asyncio
async def test_stage_upload_refuses_and_keeps_nothing_over_the_ceiling(tmp_path: Path) -> None:
    """The ceiling decides what is kept, not what arrives.

    By the time this runs the body has already been received — Starlette spools
    a file part before the handler sees it — so this is a backstop, and the
    thing worth asserting is that an oversized upload leaves no bytes behind.
    Arrival is bounded by the proxy and the frontend container instead; that
    agreement is held by ``tests/api/test_proxy_config.py``.
    """
    oversized = PDF_BYTES + b"0" * 4096

    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Too big",
            filename="lecture-01.pdf",
            read_chunk=chunk_reader(oversized),
            data_dir=tmp_path,
            learning_path_id=LEARNING_PATH_ID,
            max_bytes=64,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.TOO_LARGE.value
    assert excinfo.value.params["max_bytes"] == 64
    assert list(staging_dir(tmp_path, LEARNING_PATH_ID).iterdir()) == []


@pytest.mark.parametrize(
    ("filename", "payload", "media_type"),
    [
        ("buch.epub", EPUB_BYTES, "application/epub+zip"),
        ("aufnahme.wav", WAV_BYTES, "audio/wav"),
    ],
)
@pytest.mark.asyncio
async def test_stage_upload_accepts_a_well_formed_container(
    tmp_path: Path,
    filename: str,
    payload: bytes,
    media_type: str,
) -> None:
    staged = await stage_upload(
        title="Reading",
        filename=filename,
        read_chunk=chunk_reader(payload),
        data_dir=tmp_path,
        learning_path_id=LEARNING_PATH_ID,
        max_bytes=1024,
    )

    assert staged.media_type == media_type


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        # A plain ZIP is not an EPUB, and a RIFF holding anything else is not a
        # WAV. Checking only the outer container would accept both.
        ("buch.epub", b"PK\x03\x04" + bytes(26) + b"notes.txt" + b"hello"),
        ("aufnahme.wav", b"RIFF" + b"\x24\x00\x00\x00" + b"AVI LIST"),
    ],
)
@pytest.mark.asyncio
async def test_stage_upload_refuses_the_right_container_holding_the_wrong_thing(
    tmp_path: Path,
    filename: str,
    payload: bytes,
) -> None:
    with pytest.raises(ContentUploadRejected) as excinfo:
        await stage_upload(
            title="Disguised",
            filename=filename,
            read_chunk=chunk_reader(payload),
            data_dir=tmp_path,
            learning_path_id=LEARNING_PATH_ID,
            max_bytes=1024,
        )

    assert rejection_reason(excinfo.value) == UploadRejection.CONTENT_MISMATCH.value


@pytest.mark.asyncio
async def test_stage_upload_keeps_two_learning_paths_apart(tmp_path: Path) -> None:
    """Staged bytes carry the scope they arrived under.

    Nothing reads these files yet, so this buys nothing today — but a file
    written without an owner cannot be given one once an adapter wants to know
    whose it was.
    """
    first = await stage_upload(
        title="Graph algorithms",
        filename="lecture-01.pdf",
        read_chunk=chunk_reader(PDF_BYTES),
        data_dir=tmp_path,
        learning_path_id="12",
        max_bytes=1024,
    )
    second = await stage_upload(
        title="Graph algorithms",
        filename="lecture-01.pdf",
        read_chunk=chunk_reader(PDF_BYTES),
        data_dir=tmp_path,
        learning_path_id="34",
        max_bytes=1024,
    )

    assert first.stored_path.parent != second.stored_path.parent
    assert first.stored_path.parent == staging_dir(tmp_path, "12")
    assert second.stored_path.parent == staging_dir(tmp_path, "34")


@pytest.mark.asyncio
async def test_staging_dir_never_leaves_the_data_directory(tmp_path: Path) -> None:
    """The scope is caller data, so it is hashed rather than used as a path."""
    hostile = staging_dir(tmp_path, "../../etc")

    assert tmp_path.resolve() in hostile.resolve().parents


@pytest.mark.asyncio
async def test_stage_upload_discards_a_partial_write_when_the_client_vanishes(
    tmp_path: Path,
) -> None:
    """A refusal is not the only way this can end early.

    A dropped connection or a full disk raises something that is not a
    rejection, and the bytes already copied would otherwise stay on disk with
    nothing to reap them.
    """
    chunks = iter([PDF_BYTES, b"more"])

    async def read(_size: int) -> bytes:
        chunk = next(chunks, None)
        if chunk is None:
            msg = "client went away"
            raise ConnectionResetError(msg)
        return chunk

    with pytest.raises(ConnectionResetError):
        await stage_upload(
            title="Interrupted",
            filename="lecture-01.pdf",
            read_chunk=read,
            data_dir=tmp_path,
            learning_path_id=LEARNING_PATH_ID,
            max_bytes=1024,
        )

    assert list(staging_dir(tmp_path, LEARNING_PATH_ID).iterdir()) == []
