"""Indexer — inserts chunks with embeddings + FTS vectors into Postgres."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.document import Document, DocumentChunk
from src.ingestion.chunking import Chunk
from src.retrieval.embedders import get_embedder


async def index_chunks(
    *,
    document: Document,
    chunks: list[Chunk],
    session: AsyncSession,
    embedder: Any | None = None,
) -> int:
    """Embed + insert chunks. Returns count of inserted chunks."""
    embedder = embedder or get_embedder()
    if not chunks:
        return 0

    # Batch embed
    texts = [c.content for c in chunks]
    embeddings = await embedder.embed(texts)

    for chunk, embedding in zip(chunks, embeddings):
        db_chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=document.id,
            version=document.version,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            token_count=chunk.token_count,
            page=chunk.page,
            section=chunk.section,
            embedding=embedding,
            # tsv is auto-populated by a trigger or explicit to_tsvector() in raw SQL
            metadata_={
                "content_hash": chunk.content_hash,
                "section": chunk.section,
                "page": chunk.page,
            },
            content_hash=chunk.content_hash,
        )
        session.add(db_chunk)

    await session.flush()

    # Update tsv column with explicit SQL
    from sqlalchemy import text

    await session.execute(
        text(
            "UPDATE document_chunks SET tsv = to_tsvector('english', content) WHERE document_id = :doc_id"
        ),
        {"doc_id": document.id},
    )

    return len(chunks)
