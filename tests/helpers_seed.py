"""Shared seeding helpers for security/integration tests.

Creates documents + chunks (with embeddings + tsv) directly through the real
ingestion indexer, using deterministic IDs so assertions are stable.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, select

from apps.api.app.core.db import session_scope
from apps.api.app.models.document import Document, DocumentChunk
from apps.api.app.models.user import User
from src.ingestion.chunking import Chunk
from src.ingestion.indexer import index_chunks


@dataclass(slots=True)
class SeededDoc:
    document_id: str
    title: str
    chunk_ids: list[str]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def seed_doc(
    *,
    title: str,
    content: str,
    access_policy: dict | None = None,
    effective_from: date | None = None,
    effective_to: date | None = None,
    department: str = "general",
    version: int = 1,
    document_id: uuid.UUID | None = None,
) -> SeededDoc:
    """Insert one document + one chunk (embedded + tsv indexed)."""
    doc_id = document_id or uuid.uuid4()
    chunk = Chunk(
        content=content,
        chunk_index=0,
        page=1,
        section="1",
        token_count=len(content.split()),
        content_hash=_hash(content),
    )
    async with session_scope() as session:
        doc = Document(
            id=doc_id,
            title=title,
            doc_type="md",
            department=department,
            access_policy=access_policy or {},
            content_hash=_hash(title + content),
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        session.add(doc)
        await session.flush()
        inserted = await index_chunks(document=doc, chunks=[chunk], session=session)

    assert inserted == 1
    async with session_scope() as session:
        rows = await session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
        )
        return SeededDoc(
            document_id=str(doc_id),
            title=title,
            chunk_ids=[str(r.id) for r in rows],
        )


async def purge_docs(*document_ids: str) -> None:
    """Remove seeded documents and their chunks (test cleanup only)."""
    async with session_scope() as session:
        for doc_id in document_ids:
            uuid_id = uuid.UUID(doc_id)
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == uuid_id))
            await session.execute(delete(Document).where(Document.id == uuid_id))


async def get_user_id(email: str) -> Any:
    async with session_scope() as session:
        return str((await session.scalar(select(User).where(User.email == email))).id)
