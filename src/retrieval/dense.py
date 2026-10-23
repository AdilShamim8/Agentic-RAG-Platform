"""Dense retrieval — pgvector cosine similarity.

CRITICAL: RBAC filter is applied in the WHERE clause, BEFORE the vector search.
Never retrieve-then-filter. The effective-date window is likewise enforced
in SQL (see src/retrieval/freshness.py).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.retrieval.embedders import get_embedder
from src.retrieval.freshness import effective_window_sql
from src.retrieval.sqlfilters import optional_filter_sql
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
    window_sql, window_params = effective_window_sql(filters)
    opt_sql, opt_params = optional_filter_sql(filters)

    raw_sql = f"""
        WITH authorized AS (
            SELECT c.id, c.content, c.metadata, c.page, c.section, c.version,
                   d.title AS document_title, d.url, d.effective_from, d.effective_to,
                   d.access_policy, d.id AS document_id,
                   1 - (c.embedding <=> CAST(:q AS vector)) AS score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.deleted_at IS NULL
              AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
              {window_sql}
              {opt_sql}
            ORDER BY c.embedding <=> CAST(:q AS vector)
            LIMIT :k
        )
        SELECT * FROM authorized
        WHERE score >= :threshold
        ORDER BY score DESC
    """
    sql = text(raw_sql)

    result = await session.execute(
        sql,
        {
            **window_params,
            **opt_params,
            "q": str(q_emb[0]),
            "k": top_k,
            "user_role": user.role_slug,
            "user_projects": list(user.projects),
            "user_id": user.id,
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
