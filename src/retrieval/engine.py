"""Retrieval engine — main entry point for retrieval.

Strategies:
- dense: pgvector cosine
- lexical: Postgres FTS (ts_rank_cd)
- hybrid: dense + lexical fused with RRF
- hybrid_reranked: hybrid + cross-encoder reranking

All strategies apply RBAC filtering via the access_matches() SQL function
BEFORE the vector / FTS search. See src/security/access.py.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.observability.tracing import traced_operation
from src.reranking.base import get_reranker
from src.reranking.cross_encoder import rerank
from src.retrieval.dense import dense_retrieve
from src.retrieval.freshness import apply_freshness_boost
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.lexical import lexical_retrieve
from src.retrieval.types import ScoredChunk


async def retrieve(
    *,
    query: str,
    user: Any,
    session: AsyncSession,
    strategy: str = "hybrid_reranked",
    top_k: int = 10,
    candidate_count: int = 50,
    filters: dict | None = None,
) -> list[ScoredChunk]:
    """Retrieve chunks using the given strategy. Always applies RBAC."""
    async with traced_operation(
        "retrieve",
        strategy=strategy,
        top_k=top_k,
        candidate_count=candidate_count,
    ):
        if strategy == "dense":
            chunks = await dense_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=top_k,
                filters=filters,
            )
        elif strategy == "lexical":
            chunks = await lexical_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=top_k,
                filters=filters,
            )
        elif strategy == "hybrid":
            dense = await dense_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=candidate_count,
                filters=filters,
            )
            lexical = await lexical_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=candidate_count,
                filters=filters,
            )
            chunks = rrf_fuse(dense, lexical, top_n=top_k)
        elif strategy == "hybrid_reranked":
            dense = await dense_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=candidate_count,
                filters=filters,
            )
            lexical = await lexical_retrieve(
                query=query,
                user=user,
                session=session,
                top_k=candidate_count,
                filters=filters,
            )
            fused = rrf_fuse(dense, lexical, top_n=candidate_count)
            chunks = await rerank(get_reranker(), query=query, candidates=fused, top_k=top_k)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Apply freshness boost (penalize expired, boost currently-effective)
        chunks = apply_freshness_boost(chunks)

        return chunks
