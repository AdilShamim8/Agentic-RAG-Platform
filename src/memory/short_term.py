"""Short-term memory — last N messages of the conversation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.models.conversation import Message


async def load_short_term(*, conversation_id: str, session: AsyncSession) -> list[Message]:
    """Load the last N messages for the conversation."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(settings.memory_short_term_window)
    )
    result = await session.execute(stmt)
    messages = list(result.scalars().all())
    messages.reverse()  # chronological
    return messages


def to_context_window(messages: list[Message]) -> str:
    """Format messages as a context string for the LLM."""
    lines = []
    for m in messages:
        role = m.role.upper()
        lines.append(f"{role}: {m.content}")
    return "\n\n".join(lines)
