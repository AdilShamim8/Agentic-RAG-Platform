"""Memory service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def list_memories(*, user_id: str, session: AsyncSession) -> list:
    # TODO: implement
    return []


async def update_memory(*, memory_id: str, user_id: str, content: str, session: AsyncSession):
    # TODO: implement + write audit log
    return None


async def delete_memory(*, memory_id: str, user_id: str, session: AsyncSession) -> bool:
    # TODO: implement + write audit log
    return False


async def export_memories(*, user_id: str, session: AsyncSession) -> list:
    # TODO: implement
    return []
