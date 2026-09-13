"""Validation and staging for learner-supplied content-source uploads.

Ingestion adapters are not in this phase's scope, so an accepted upload lands
in a staging directory carrying the ``queued`` state and nothing reads it back
yet. What does exist here is the boundary check every later adapter can rely
on: a size ceiling, an extension allowlist, and a magic-byte sniff that has to
agree with the extension. Browser-supplied metadata — the filename and the part
header's ``Content-Type`` — decides nothing on its own, because a caller
controls both.

**Where the upload is actually bounded.** Not here. Starlette spools a whole
file part to a temporary file before a handler sees it, so by the time
:func:`stage_upload` reads its first chunk the body has already been received.
What bounds receipt is the hop in front: Caddy's ``request_body max_size`` on
``/api/content-sources/uploads``, and ``BODY_SIZE_LIMIT`` on the SvelteKit
container for a browser posting through the form action. The check below is a
post-receipt backstop — it stops an oversized body from being *kept*, and it is
the only limit a caller reaching the API directly, inside the network, meets at
all. Because ``content_upload_max_bytes`` is pinned equal to the proxy ceiling,
it does not normally fire behind the proxy; that equality is the point, and
``tests/api/test_proxy_config.py`` is what holds it.

Staging is scoped per learning path. Nothing reads these files yet, so the
scoping buys nothing today — but a file written without an owner cannot be
given one later, and every other read path in this codebase is scoped.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
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
class Signature:
    """Bytes a container must carry at a fixed offset.

    ``alternatives`` are read as "any of these"; a format listing several
    :class:`Signature` entries requires *all* of them, which is what separates
    an EPUB from any other ZIP and a WAV from any other RIFF container.
    """

    offset: int
    alternatives: tuple[bytes, ...]

    def matches(self, head: bytes) -> bool:
        window = head[self.offset :]
        return any(window.startswith(candidate) for candidate in self.alternatives)

    @property
    def end(self) -> int:
        return self.offset + max(len(candidate) for candidate in self.alternatives)


@dataclass(frozen=True, slots=True)
class UploadFormat:
    """One accepted format: what it is called, and what its bytes start with."""

    media_type: str
    extension: str
    signatures: tuple[Signature, ...]


# Ordered by how a learner is most likely to arrive: reading material first,
# then recordings. `ftyp` sits at offset 4 in the ISO base media container,
# which is why an offset is part of every signature rather than assumed zero.
#
# EPUB and WAV each need two: their outer container is a ZIP and a RIFF, which
# say nothing about the payload. The EPUB spec requires an uncompressed
# `mimetype` entry first in the archive, which puts its value at offset 38;
# RIFF puts its form type at offset 8.
SUPPORTED_FORMATS: tuple[UploadFormat, ...] = (
    UploadFormat("application/pdf", ".pdf", (Signature(0, (b"%PDF-",)),)),
    UploadFormat(
        "application/epub+zip",
        ".epub",
        (
            Signature(0, (b"PK\x03\x04",)),
            Signature(30, (b"mimetype",)),
            Signature(38, (b"application/epub+zip",)),
        ),
    ),
    UploadFormat(
        "audio/mpeg",
        ".mp3",
        (Signature(0, (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),),
    ),
    UploadFormat("audio/mp4", ".m4a", (Signature(4, (b"ftyp",)),)),
    UploadFormat("video/mp4", ".mp4", (Signature(4, (b"ftyp",)),)),
    UploadFormat(
        "audio/wav",
        ".wav",
        (Signature(0, (b"RIFF",)), Signature(8, (b"WAVE",))),
    ),
)

SIGNATURE_WINDOW_BYTES = max(
    signature.end for fmt in SUPPORTED_FORMATS for signature in fmt.signatures
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
    return all(signature.matches(head) for signature in upload_format.signatures)


def staging_dir(data_dir: Path, learning_path_id: str) -> Path:
    """Where one learning path's staged uploads live.

    The id is hashed into a hex name rather than used literally: it arrives
    from a session record as a string, and a path segment built from caller
    data is a traversal waiting to be found.
    """
    scope = uuid.uuid5(uuid.NAMESPACE_OID, learning_path_id).hex
    return data_dir / STAGING_DIR_NAME / scope


async def stage_upload(
    *,
    title: str | None,
    filename: str | None,
    read_chunk: Callable[[int], Awaitable[bytes]],
    data_dir: Path,
    learning_path_id: str,
    max_bytes: int,
) -> StagedUpload:
    """Validate one multipart upload and stage its bytes for later ingestion.

    ``read_chunk`` is the part's reader rather than its bytes, so an oversized
    body is abandoned partway through being copied rather than after. It is not
    what stops an oversized body being *received* — see the module docstring.
    """
    resolved_title = normalize_title(title)
    upload_format = format_for_filename(filename)

    scoped = anyio.Path(staging_dir(data_dir, learning_path_id))
    await scoped.mkdir(parents=True, exist_ok=True, mode=0o700)

    upload_id = uuid.uuid4().hex
    target = scoped / f"{upload_id}{upload_format.extension}"
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
    # Every exit that is not a success discards the partial file, not just a
    # refusal: a client that disconnects mid-copy, a full disk, or a cancelled
    # task would each otherwise leave bytes behind that nothing ever reaps.
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
    except BaseException:
        await _discard(target)
        raise

    return byte_size


async def _discard(target: anyio.Path) -> None:
    """Remove a partial file, tolerating one that was never created.

    Shielded because the cancellation this runs under would otherwise cancel
    the cleanup too, which is exactly the case that leaves bytes behind.
    """
    with anyio.CancelScope(shield=True), suppress(OSError):
        await target.unlink(missing_ok=True)
