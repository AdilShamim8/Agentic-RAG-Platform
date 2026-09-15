"""Memory retrieval — hybrid search over user's long-term memories.

Always filtered by user_id — never cross-user.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.memory import Memory


async def search_memories(
    *,
    query: str,
    user_id: str,
    session: AsyncSession,
    top_k: int = 5,
) -> list[Memory]:
    """Search a user's long-term memory.

    CRITICAL: filter by user_id ALWAYS. Never retrieve another user's memories.
    Filter out expired and superseded memories.
    """
    now = datetime.now(UTC)
    stmt = (
        select(Memory)
        .where(
            and_(
                Memory.user_id == user_id,  # ALWAYS
                Memory.deleted_at.is_(None),
                Memory.superseded_by.is_(None),
                (Memory.expires_at.is_(None)) | (Memory.expires_at >= now),
            )
        )
        .order_by(Memory.created_at.desc())
        .limit(top_k * 2)
    )

    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    # In production: do hybrid retrieval (dense over content + keyword on scope)
    # For now: simple keyword match
    query_lower = query.lower()
    scored = []
    for m in candidates:
        score = sum(1.0 for word in query_lower.split() if word in m.content.lower()) * m.confidence
        scored.append((m, score))
    scored.sort(key=lambda x: -x[1])

    return [m for m, _ in scored[:top_k]]
