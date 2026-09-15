"""Conversation service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def list_conversations(*, user_id: str, session: AsyncSession) -> list:
    # TODO: implement
    return []


async def create_conversation(*, user_id: str, title: str, session: AsyncSession):
    # TODO: implement
    pass


async def get_conversation(*, conversation_id: str, user_id: str, session: AsyncSession):
    # TODO: implement
    return None
