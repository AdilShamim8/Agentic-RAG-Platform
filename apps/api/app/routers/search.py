"""Search endpoint — raw retrieval without generation. Useful for evaluation and admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    strategy: str = "hybrid_reranked"  # dense | lexical | hybrid | hybrid_reranked
    top_k: int = 10
    candidate_count: int = 50
    filters: dict = Field(default_factory=dict)


class ScoredChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    page: int | None = None
    section: str | None = None
    url: str | None = None
    version: int
    effective_from: str | None = None
    effective_to: str | None = None


class SearchResponse(BaseModel):
    results: list[ScoredChunk]
    trace_id: str
    latency_ms: int


from apps.api.app.services.search_service import search_chunks  # noqa: E402


@router.post("", response_model=SearchResponse)
@router.post("/", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SearchResponse:
    return await search_chunks(
        query=body.query,
        user=user,
        session=session,
        strategy=body.strategy,
        top_k=body.top_k,
        candidate_count=body.candidate_count,
        filters=body.filters,
    )
