"""Seed the evaluation fixture corpus into the database.

Idempotent: upserts by fixed doc UUID; skips re-embedding when the
document's content hash is unchanged. Chunk UUIDs are deterministic
(uuid5 of "agentic-rag-fixture:{doc_id}:{index}") so golden-dataset
references resolve across environments.

Usage: python -m scripts.seed_fixtures
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import date

from sqlalchemy import select

from apps.api.app.core.db import session_scope
from apps.api.app.models.document import Document, DocumentChunk, DocumentVersion
from evals.fixtures import fixture_chunk_id, load_fixture_spec
from src.retrieval.embedders import get_embedder


def _doc_hash(doc: dict) -> str:
    blob = doc["title"] + "\x00" + "\x00".join(doc["chunks"])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def seed_fixtures() -> int:
    specs = load_fixture_spec()
    embedder = get_embedder()
    created = updated = unchanged = 0

    async with session_scope() as session:
        for doc in specs:
            digest = _doc_hash(doc)
            existing = await session.get(Document, uuid.UUID(doc["doc_id"]))
            if existing is not None and existing.content_hash == digest:
                unchanged += 1
                continue

            if existing is None:
                existing = Document(
                    id=uuid.UUID(doc["doc_id"]),
                    title=doc["title"],
                    doc_type=doc["doc_type"],
                    department=doc["department"],
                    access_policy=doc["access_policy"],
                    content_hash=digest,
                    version=doc.get("version", 1),
                    effective_from=(
                        date.fromisoformat(doc["effective_from"]) if doc["effective_from"] else None
                    ),
                    effective_to=(
                        date.fromisoformat(doc["effective_to"]) if doc["effective_to"] else None
                    ),
                )
                session.add(existing)
                created += 1
            else:
                existing.title = doc["title"]
                existing.access_policy = doc["access_policy"]
                existing.content_hash = digest
                existing.effective_from = (
                    date.fromisoformat(doc["effective_from"]) if doc["effective_from"] else None
                )
                existing.effective_to = (
                    date.fromisoformat(doc["effective_to"]) if doc["effective_to"] else None
                )
                existing.deleted_at = None
                updated += 1
            await session.flush()

            # (Re-)index chunks deterministically
            existing_rows = await session.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == existing.id)
            )
            for row in list(existing_rows):
                await session.delete(row)
            await session.flush()

            embeddings = await embedder.embed(doc["chunks"])
            for index, (content, embedding) in enumerate(zip(doc["chunks"], embeddings)):
                session.add(
                    DocumentChunk(
                        id=uuid.UUID(fixture_chunk_id(doc["doc_id"], index)),
                        document_id=existing.id,
                        version=doc.get("version", 1),
                        chunk_index=index,
                        content=content,
                        token_count=len(content.split()),
                        page=None,
                        section=None,
                        embedding=embedding,
                        metadata_={"fixture": True},
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    )
                )
            await session.flush()

            # tsv for lexical retrieval
            from sqlalchemy import text

            await session.execute(
                text(
                    "UPDATE document_chunks SET tsv = to_tsvector('english', content) "
                    "WHERE document_id = :doc_id"
                ),
                {"doc_id": existing.id},
            )

            # Version record (idempotent by version number)
            has_version = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == existing.id,
                    DocumentVersion.version == doc.get("version", 1),
                )
            )
            if has_version is None:
                session.add(
                    DocumentVersion(
                        document_id=existing.id,
                        version=doc.get("version", 1),
                        content_hash=digest,
                        change_summary="fixture corpus",
                    )
                )

    print(
        f"Fixture corpus seeded: {created} created, {updated} updated, "
        f"{unchanged} unchanged ({len(specs)} total)"
    )
    return len(specs)


if __name__ == "__main__":
    asyncio.run(seed_fixtures())
