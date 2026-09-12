"""Validation and staging for learner-supplied content-source uploads.

Ingestion adapters are not in this phase's scope, so an accepted upload lands
in a staging directory carrying the ``queued`` state and nothing reads it back
yet. What does exist here is the boundary check every later adapter can rely
on: a size ceiling, an extension allowlist, and a magic-byte sniff that has to
agree with the extension. Browser-supplied metadata — the filename and the part
header's ``Content-Type`` — decides nothing on its own, because a caller
controls both.

The stream is written in chunks and abandoned the moment it crosses the
ceiling, so refusing an oversized upload costs the disk one chunk rather than
the whole file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import anyio

from sophia.domain.errors import ContentUploadRejected

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

CHUNK_BYTES = 1 << 20
TITLE_MAX_LENGTH = 200
STAGING_DIR_NAME = "content-uploads"
"""Staging lives beside the rest of the application data, never in the repo."""


class UploadRejection(StrEnum):
    """Why the boundary refused an upload, as the form needs to phrase it."""

    TITLE_REQUIRED = "title_required"
    TITLE_TOO_LONG = "title_too_long"
    FILE_REQUIRED = "file_required"
    EMPTY_FILE = "empty_file"
    TOO_LARGE = "too_large"
    UNSUPPORTED_TYPE = "unsupported_type"
    CONTENT_MISMATCH = "content_mismatch"


class IngestionState(StrEnum):
    """Where an accepted upload sits in the processing that follows it.

    Transcription and indexing take minutes, so the upload request answers with
    ``QUEUED`` rather than holding the connection open until they finish.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    FAILED = "failed"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class UploadFormat:
    """One accepted format: what it is called, and what its bytes start with."""

    media_type: str
    extension: str
    signatures: tuple[bytes, ...]
    signature_offset: int = 0


# Ordered by how a learner is most likely to arrive: reading material first,
# then recordings. `ftyp` sits at offset 4 in the ISO base media container,
# which is why the offset is part of the format rather than assumed to be zero.
SUPPORTED_FORMATS: tuple[UploadFormat, ...] = (
    UploadFormat("application/pdf", ".pdf", (b"%PDF-",)),
    UploadFormat("application/epub+zip", ".epub", (b"PK\x03\x04",)),
    UploadFormat("audio/mpeg", ".mp3", (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    UploadFormat("audio/mp4", ".m4a", (b"ftyp",), signature_offset=4),
    UploadFormat("video/mp4", ".mp4", (b"ftyp",), signature_offset=4),
    UploadFormat("audio/wav", ".wav", (b"RIFF",)),
)

SIGNATURE_WINDOW_BYTES = max(
    fmt.signature_offset + len(signature)
    for fmt in SUPPORTED_FORMATS
    for signature in fmt.signatures
)


@dataclass(frozen=True, slots=True)
class StagedUpload:
    """An upload that passed the boundary and is waiting for an adapter."""

    upload_id: str
    title: str
    media_type: str
    byte_size: int
    state: IngestionState
    stored_path: Path


def normalize_title(raw: str | None) -> str:
    """Collapse a submitted title to what gets stored, or raise if unusable."""
    title = " ".join((raw or "").split())
    if not title:
        raise ContentUploadRejected(
            "upload title is required",
            {"reason": UploadRejection.TITLE_REQUIRED.value},
        )
    if len(title) > TITLE_MAX_LENGTH:
        raise ContentUploadRejected(
            "upload title is too long",
            {"reason": UploadRejection.TITLE_TOO_LONG.value, "max_length": TITLE_MAX_LENGTH},
        )
    return title


def format_for_filename(filename: str | None) -> UploadFormat:
    """Pick the accepted format a filename claims, or raise if it claims none.

    The name is read only for its extension, and only through ``PurePosixPath``
    so a caller cannot smuggle a directory component into the staging path.
    """
    if not filename:
        raise ContentUploadRejected(
            "upload file is required",
            {"reason": UploadRejection.FILE_REQUIRED.value},
        )

    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    for candidate in SUPPORTED_FORMATS:
        if candidate.extension == extension:
            return candidate

    raise ContentUploadRejected(
        "upload file type is not supported",
        {
            "reason": UploadRejection.UNSUPPORTED_TYPE.value,
            "accepted": accepted_extensions(),
        },
    )


def accepted_extensions() -> str:
    """The allowlist as the form shows it, so both ends name the same set."""
    return " ".join(fmt.extension for fmt in SUPPORTED_FORMATS)


def signature_matches(upload_format: UploadFormat, head: bytes) -> bool:
    """Whether the leading bytes are what this format's containers start with."""
    return any(
        head[upload_format.signature_offset :].startswith(signature)
        for signature in upload_format.signatures
    )


async def stage_upload(
    *,
    title: str | None,
    filename: str | None,
    read_chunk: Callable[[int], Awaitable[bytes]],
    data_dir: Path,
    max_bytes: int,
) -> StagedUpload:
    """Validate one multipart upload and stage its bytes for later ingestion.

    ``read_chunk`` is the part's reader rather than its bytes: a 512 MB ceiling
    that only applies after the whole body is already in memory is not a
    ceiling.
    """
    resolved_title = normalize_title(title)
    upload_format = format_for_filename(filename)

    staging_dir = anyio.Path(data_dir) / STAGING_DIR_NAME
    await staging_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    upload_id = uuid.uuid4().hex
    target = staging_dir / f"{upload_id}{upload_format.extension}"
    byte_size = await _write_stream(target, read_chunk, upload_format, max_bytes)

    return StagedUpload(
        upload_id=upload_id,
        title=resolved_title,
        media_type=upload_format.media_type,
        byte_size=byte_size,
        state=IngestionState.QUEUED,
        stored_path=Path(target),
    )


async def _write_stream(
    target: anyio.Path,
    read_chunk: Callable[[int], Awaitable[bytes]],
    upload_format: UploadFormat,
    max_bytes: int,
) -> int:
    byte_size = 0
    head = b""
    try:
        async with await target.open("wb") as stored:
            while chunk := await read_chunk(CHUNK_BYTES):
                if len(head) < SIGNATURE_WINDOW_BYTES:
                    head = (head + chunk)[:SIGNATURE_WINDOW_BYTES]
                byte_size += len(chunk)
                if byte_size > max_bytes:
                    raise ContentUploadRejected(
                        "upload exceeds the size limit",
                        {"reason": UploadRejection.TOO_LARGE.value, "max_bytes": max_bytes},
                    )
                await stored.write(chunk)

        if byte_size == 0:
            raise ContentUploadRejected(
                "upload file is empty",
                {"reason": UploadRejection.EMPTY_FILE.value},
            )
        if not signature_matches(upload_format, head):
            raise ContentUploadRejected(
                "upload contents do not match its file type",
                {
                    "reason": UploadRejection.CONTENT_MISMATCH.value,
                    "expected": upload_format.media_type,
                },
            )
    except ContentUploadRejected:
        await _discard(target)
        raise

    return byte_size


async def _discard(target: anyio.Path) -> None:
    """Remove a partial file, tolerating one that was never created."""
    await target.unlink(missing_ok=True)
