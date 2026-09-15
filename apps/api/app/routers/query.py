"""Query endpoint — the main Agentic RAG entrypoint."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user

router = APIRouter()


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None = None
    section: str | None = None
    url: str | None = None
    snippet: str = Field(..., description="The text span from the chunk that supports the claim")
    verified: bool


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    conversation_id: str | None = None
    retrieval_strategy: str = "hybrid_reranked"  # dense | lexical | hybrid | hybrid_reranked
    top_k: int | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    trace_id: str
    conversation_id: str
    confidence: str  # low | medium | high
    failure: str | None = None
    metadata: dict = Field(default_factory=dict)


from apps.api.app.services.query_service import run_agentic_query  # noqa: E402


@router.post("", response_model=QueryResponse)
@router.post("/", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueryResponse:
    trace_id = str(uuid.uuid4())
    return await run_agentic_query(
        query=body.query,
        user=user,
        session=session,
        conversation_id=body.conversation_id,
        retrieval_strategy=body.retrieval_strategy,
        top_k=body.top_k,
        trace_id=trace_id,
    )
