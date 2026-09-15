"""Dense retrieval — pgvector cosine similarity.

CRITICAL: RBAC filter is applied in the WHERE clause, BEFORE the vector search.
Never retrieve-then-filter.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.retrieval.embedders import get_embedder
from src.retrieval.types import ScoredChunk


async def dense_retrieve(
    *,
    query: str,
    user: Any,
    session: AsyncSession,
    top_k: int = 20,
    filters: dict | None = None,
) -> list[ScoredChunk]:
    embedder = get_embedder()
    q_emb = await embedder.embed([query])
    filters = filters or {}

    sql = text("""
        WITH authorized AS (
            SELECT c.id, c.content, c.metadata, c.page, c.section, c.version,
                   d.title AS document_title, d.url, d.effective_from, d.effective_to,
                   d.access_policy, d.id AS document_id,
                   1 - (c.embedding <=> CAST(:q AS vector)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL
              AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
              AND (:department IS NULL OR d.department = :department)
              AND (:doc_type IS NULL OR d.doc_type = :doc_type)
            ORDER BY c.embedding <=> CAST(:q AS vector)
            LIMIT :k
        )
        SELECT * FROM authorized
        WHERE score >= :threshold
        ORDER BY score DESC
    """)

    result = await session.execute(
        sql,
        {
            "q": str(q_emb[0]),
            "k": top_k,
            "user_role": user.role_slug,
            "user_projects": list(user.projects),
            "user_id": user.id,
            "department": filters.get("department"),
            "doc_type": filters.get("doc_type"),
            "threshold": 0.2,
        },
    )
    rows = result.mappings().all()
    return [_row_to_chunk(r) for r in rows]


def _row_to_chunk(r: Any) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(r["id"]),
        document_id=str(r["document_id"]),
        document_title=r["document_title"],
        content=r["content"],
        score=float(r["score"]),
        page=r.get("page"),
        section=r.get("section"),
        url=r.get("url"),
        version=r.get("version", 1),
        effective_from=r.get("effective_from"),
        effective_to=r.get("effective_to"),
        access_policy=r.get("access_policy"),
    )
