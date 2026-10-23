"""Query endpoint — the main Agentic RAG entrypoint."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_auth_user
from apps.api.app.schemas import QueryRequest, QueryResponse

router = APIRouter()


from apps.api.app.services.query_service import run_agentic_query  # noqa: E402


@router.post("", response_model=QueryResponse)
@router.post("/", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    user: Annotated[AuthUser, Depends(get_auth_user)],
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
