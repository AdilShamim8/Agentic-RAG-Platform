"""Search endpoint — raw retrieval without generation. Useful for evaluation and admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_auth_user
from apps.api.app.schemas import SearchRequest, SearchResponse

router = APIRouter()


from apps.api.app.services.search_service import search_chunks  # noqa: E402


@router.post("", response_model=SearchResponse)
@router.post("/", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    user: Annotated[AuthUser, Depends(get_auth_user)],
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
