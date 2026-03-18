"""Course material scraping, chunking, and ChromaDB indexing."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from sophia.adapters.embedder import SentenceTransformerEmbedder
from sophia.adapters.knowledge_store import ChromaKnowledgeStore
from sophia.adapters.moodle import extract_full_pdf_text
from sophia.domain.models import CourseMaterial, HermesConfig, KnowledgeChunk
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    import aiosqlite

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_CHUNK_SIZE = 500  # chars per chunk
_CHUNK_OVERLAP = 100  # char overlap between chunks

_PDF_MIMETYPES = {"application/pdf"}


def _create_embedder(app: AppContainer) -> SentenceTransformerEmbedder:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        config = HermesConfig()
    return SentenceTransformerEmbedder(config.embeddings)


def _create_store(app: AppContainer) -> ChromaKnowledgeStore:
    return ChromaKnowledgeStore(app.settings.data_dir / "knowledge")


def _is_pdf_resource(module: Any) -> tuple[bool, str | None, str | None, int | None]:
    """Check if a ModuleInfo contains a PDF file. Returns (is_pdf, url, mimetype, size)."""
    for content in module.contents:
        if content.mimetype in _PDF_MIMETYPES or content.filename.lower().endswith(".pdf"):
            return True, content.fileurl, content.mimetype, content.filesize
    return False, None, None, None


async def _download_pdf(app: AppContainer, url: str) -> bytes:
    """Download a PDF file via the app's HTTP client."""
    response = await app.http.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.content


async def _url_exists(db: aiosqlite.Connection, course_id: int, url: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM course_materials WHERE course_id = ? AND url = ?",
        (course_id, url),
    )
    return await cursor.fetchone() is not None


async def scrape_course_materials(app: AppContainer, course_id: int) -> list[CourseMaterial]:
    """Scrape TUWEL course for PDF resources and persist to course_materials."""
    modules = await app.moodle.get_course_resources([course_id])

    new_materials: list[CourseMaterial] = []
    for module in modules:
        is_pdf, file_url, mimetype, file_size = _is_pdf_resource(module)
        if not is_pdf or not file_url:
            continue

        if await _url_exists(app.db, course_id, file_url):
            continue

        try:
            pdf_bytes = await _download_pdf(app, file_url)
            pdf_text = extract_full_pdf_text(pdf_bytes)
        except Exception:  # noqa: BLE001
            log.warning("pdf_extraction_failed", module_id=module.id, url=file_url)
            pdf_text = ""

        await app.db.execute(
            "INSERT INTO course_materials"
            " (course_id, module_id, name, url, mimetype, file_size_bytes, pdf_text, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (course_id, module.id, module.name, file_url, mimetype, file_size, pdf_text),
        )
        await app.db.commit()

        cursor = await app.db.execute(
            "SELECT id, created_at FROM course_materials WHERE course_id = ? AND url = ?",
            (course_id, file_url),
        )
        row = await cursor.fetchone()
        assert row is not None
        mat_id, created_at = row

        new_materials.append(
            CourseMaterial(
                id=mat_id,
                course_id=course_id,
                module_id=module.id,
                name=module.name,
                url=file_url,
                mimetype=mimetype,
                file_size_bytes=file_size,
                status="pending",
                created_at=created_at,
            )
        )

    return new_materials


def chunk_pdf_text(text: str, material_id: int) -> list[KnowledgeChunk]:
    """Split PDF text into overlapping chunks for embedding.

    Uses a character-based sliding window of _CHUNK_SIZE chars with _CHUNK_OVERLAP overlap.
    Tries to break at paragraph boundaries (double newline) when possible.
    """
    if not text or not text.strip():
        return []

    chunks: list[KnowledgeChunk] = []
    pos = 0
    chunk_index = 0

    while pos < len(text):
        end = pos + _CHUNK_SIZE

        if end >= len(text):
            chunk_text = text[pos:]
        else:
            # Try to break at a paragraph boundary within the last portion of the chunk
            search_start = max(pos, end - _CHUNK_OVERLAP)
            boundary = text.rfind("\n\n", search_start, end)
            if boundary > pos:
                end = boundary
            chunk_text = text[pos:end]

        chunks.append(
            KnowledgeChunk(
                chunk_id=f"mat-{material_id}_{chunk_index}",
                episode_id=f"mat-{material_id}",
                chunk_index=chunk_index,
                text=chunk_text,
                start_time=0.0,
                end_time=0.0,
                source="pdf",
            )
        )
        chunk_index += 1

        if end >= len(text):
            break
        pos = end - _CHUNK_OVERLAP

    return chunks


async def index_materials(app: AppContainer, course_id: int) -> int:
    """Embed and index all unindexed materials for a course. Returns chunk count."""
    cursor = await app.db.execute(
        "SELECT id, pdf_text FROM course_materials"
        " WHERE course_id = ? AND status = 'pending' AND chunk_count = 0",
        (course_id,),
    )
    rows = await cursor.fetchall()

    total_chunks = 0
    embedder: SentenceTransformerEmbedder | None = None
    store: ChromaKnowledgeStore | None = None

    for mat_id, pdf_text in rows:
        if not pdf_text or not pdf_text.strip():
            await app.db.execute(
                "UPDATE course_materials SET status = 'completed', chunk_count = 0 WHERE id = ?",
                (mat_id,),
            )
            await app.db.commit()
            continue

        chunks = chunk_pdf_text(pdf_text, mat_id)
        if not chunks:
            continue

        if embedder is None:
            embedder = _create_embedder(app)
            store = _create_store(app)
        assert store is not None

        embeddings: list[list[float]] = await asyncio.to_thread(
            embedder.embed, [c.text for c in chunks]
        )
        await asyncio.to_thread(store.add_chunks, chunks, embeddings)

        await app.db.execute(
            "UPDATE course_materials SET status = 'completed', chunk_count = ? WHERE id = ?",
            (len(chunks), mat_id),
        )
        await app.db.commit()

        total_chunks += len(chunks)
        log.info("material_indexed", material_id=mat_id, chunks=len(chunks))

    return total_chunks
