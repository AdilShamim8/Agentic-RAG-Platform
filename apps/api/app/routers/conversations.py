"""Conversations endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user
from apps.api.app.services.conversation_service import (
    create_conversation,
    get_conversation,
    list_conversations,
)

router = APIRouter()


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int


class ConversationDetail(ConversationOut):
    messages: list[dict]


@router.get("", response_model=list[ConversationOut])
async def list_convos(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationOut]:
    return await list_conversations(user_id=user.id, session=session)


@router.post("", response_model=ConversationOut)
async def create_convo(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    title: str = "New conversation",
) -> ConversationOut:
    return await create_conversation(user_id=user.id, title=title, session=session)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_convo(
    conversation_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetail:
    convo = await get_conversation(
        conversation_id=conversation_id, user_id=user.id, session=session
    )
    if convo is None:
        raise HTTPException(404, "Conversation not found")
    return convo
