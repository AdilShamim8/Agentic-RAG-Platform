"""Memory endpoints — list, edit, delete, export."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user
from apps.api.app.services.memory_service import (
    delete_memory,
    export_memories,
    list_memories,
    update_memory,
)

router = APIRouter()


class MemoryOut(BaseModel):
    id: str
    scope: str  # user_pref | project_context | recurring_question | decision
    content: str
    source: str
    confidence: float
    expires_at: str | None
    created_at: str
    updated_at: str


class MemoryUpdate(BaseModel):
    content: str


@router.get("", response_model=list[MemoryOut])
async def list_user_memories(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MemoryOut]:
    return await list_memories(user_id=user.id, session=session)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_user_memory(
    memory_id: str,
    body: MemoryUpdate,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemoryOut:
    memory = await update_memory(
        memory_id=memory_id, user_id=user.id, content=body.content, session=session
    )
    if memory is None:
        raise HTTPException(404, "Memory not found")
    return memory


@router.delete("/{memory_id}")
async def delete_user_memory(
    memory_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    deleted = await delete_memory(memory_id=memory_id, user_id=user.id, session=session)
    if not deleted:
        raise HTTPException(404, "Memory not found")
    return {"status": "deleted", "memory_id": memory_id}


@router.get("/export")
async def export_user_memories(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """GDPR-friendly export."""
    data = await export_memories(user_id=user.id, session=session)
    return {"user_id": user.id, "memories": data, "count": len(data)}
