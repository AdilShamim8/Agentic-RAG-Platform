"""Memory service — list, update, delete, export (per-user, audited).

Previously four TODO stubs. All operations are scoped to the requesting
user's own memories (ownership check on every path) and privileged
mutations write audit log rows. Deletion is a soft delete (deleted_at)
consistent with the memory-retrieval filters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.audit import AuditLog
from apps.api.app.models.memory import Memory


def _to_out(m: Memory) -> dict:
    return {
        "id": str(m.id),
        "scope": m.scope,
        "content": m.content,
        "source": m.source,
        "confidence": m.confidence,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat() if m.updated_at else m.created_at.isoformat(),
    }


async def _get_owned(memory_id: str, user_id: str, session: AsyncSession) -> Memory | None:
    try:
        pk = uuid.UUID(memory_id)
    except ValueError:
        return None
    m = await session.get(Memory, pk)
    if m is None or m.deleted_at is not None:
        return None
    if str(m.user_id) != user_id:
        return None  # foreign memory: indistinguishable from missing
    return m


async def list_memories(*, user_id: str, session: AsyncSession) -> list[dict]:
    """List the user's live memories (not deleted, not superseded, not expired)."""
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(Memory)
        .where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.deleted_at.is_(None),
            Memory.superseded_by.is_(None),
        )
        .order_by(Memory.created_at.desc())
    )
    live = [m for m in rows if m.expires_at is None or m.expires_at >= now]
    return [_to_out(m) for m in live]


async def update_memory(
    *, memory_id: str, user_id: str, content: str, session: AsyncSession
) -> dict | None:
    m = await _get_owned(memory_id, user_id, session)
    if m is None:
        return None
    m.content = content
    m.updated_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_id=uuid.UUID(user_id),
            action="memory.update",
            target=str(m.id),
            metadata_={"bytes": len(content)},
        )
    )
    await session.flush()
    return _to_out(m)


async def delete_memory(*, memory_id: str, user_id: str, session: AsyncSession) -> bool:
    m = await _get_owned(memory_id, user_id, session)
    if m is None:
        return False
    m.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_id=uuid.UUID(user_id),
            action="memory.delete",
            target=str(m.id),
            metadata_={},
        )
    )
    await session.flush()
    return True


async def export_memories(*, user_id: str, session: AsyncSession) -> list[dict]:
    """GDPR-friendly export of all the user's non-deleted memories."""
    rows = await session.scalars(
        select(Memory)
        .where(Memory.user_id == uuid.UUID(user_id), Memory.deleted_at.is_(None))
        .order_by(Memory.created_at.asc())
    )
    return [_to_out(m) for m in rows]
