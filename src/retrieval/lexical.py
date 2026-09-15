"""Lexical retrieval — Postgres FTS with ts_rank_cd scoring."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.retrieval.types import ScoredChunk


async def lexical_retrieve(
    *,
    query: str,
    user: Any,
    session: AsyncSession,
    top_k: int = 20,
    filters: dict | None = None,
) -> list[ScoredChunk]:
    filters = filters or {}
    sql = text("""
        SELECT c.id, c.content, c.metadata, c.page, c.section, c.version,
               d.title AS document_title, d.url, d.effective_from, d.effective_to,
               d.access_policy, d.id AS document_id,
               ts_rank_cd(c.tsv, plainto_tsquery('english', :q)) AS score
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.deleted_at IS NULL
          AND c.tsv @@ plainto_tsquery('english', :q)
          AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
          AND (:department IS NULL OR d.department = :department)
          AND (:doc_type IS NULL OR d.doc_type = :doc_type)
        ORDER BY score DESC
        LIMIT :k
    """)
    result = await session.execute(
        sql,
        {
            "q": query,
            "k": top_k,
            "user_role": user.role_slug,
            "user_projects": list(user.projects),
            "user_id": user.id,
            "department": filters.get("department"),
            "doc_type": filters.get("doc_type"),
        },
    )
    rows = [dict(r) for r in result.mappings().all()]

    # Normalize scores to 0..1
    max_score = max((float(r["score"]) for r in rows), default=1.0)
    if max_score > 0:
        for r in rows:
            r["score"] = float(r["score"]) / max_score

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
