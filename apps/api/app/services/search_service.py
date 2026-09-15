"""Search service — raw retrieval (no generation)."""

from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.deps.auth import AuthUser
from apps.api.app.routers.search import ScoredChunk, SearchResponse
from src.observability.tracing import traced_operation
from src.retrieval.engine import retrieve


async def search_chunks(
    *,
    query: str,
    user: AuthUser,
    session: AsyncSession,
    strategy: str,
    top_k: int,
    candidate_count: int,
    filters: dict,
) -> SearchResponse:
    trace_id = str(uuid.uuid4())
    start = time.perf_counter()

    async with traced_operation("search", trace_id=trace_id, strategy=strategy):
        chunks = await retrieve(
            query=query,
            user=user,
            session=session,
            strategy=strategy,
            top_k=top_k,
            candidate_count=candidate_count,
            filters=filters,
        )

    latency_ms = int((time.perf_counter() - start) * 1000)

    return SearchResponse(
        results=[
            ScoredChunk(
                chunk_id=str(c.chunk_id),
                document_id=str(c.document_id),
                document_title=c.document_title,
                content=c.content,
                score=c.score,
                page=c.page,
                section=c.section,
                url=c.url,
                version=c.version,
                effective_from=c.effective_from.isoformat() if c.effective_from else None,
                effective_to=c.effective_to.isoformat() if c.effective_to else None,
            )
            for c in chunks
        ],
        trace_id=trace_id,
        latency_ms=latency_ms,
    )
