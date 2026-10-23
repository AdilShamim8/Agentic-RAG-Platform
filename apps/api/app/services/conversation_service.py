"""Conversation service — list, create, get (ownership enforced).

Previously all three functions were TODO stubs (empty list / pass / None).
Conversations are strictly per-user: a request for another user's
conversation id returns None (the router maps that to 404), so foreign
ids neither leak content nor confirm existence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.conversation import Conversation, Message


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def list_conversations(*, user_id: str, session: AsyncSession) -> list[dict]:
    """List a user's conversations with message counts (newest first)."""
    stmt = (
        select(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            func.count(Message.id).label("message_count"),
        )
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == uuid.UUID(user_id))
        .group_by(Conversation.id)
        .order_by(Conversation.created_at.desc())
        .limit(100)
    )
    result = await session.execute(stmt)
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "created_at": row.created_at.isoformat(),
            "message_count": int(row.message_count or 0),
        }
        for row in result.all()
    ]


async def create_conversation(*, user_id: str, title: str, session: AsyncSession) -> dict:
    convo = Conversation(id=uuid.uuid4(), user_id=uuid.UUID(user_id), title=title)
    session.add(convo)
    await session.flush()
    return {
        "id": str(convo.id),
        "title": convo.title,
        "created_at": convo.created_at.isoformat(),
        "message_count": 0,
    }


async def get_conversation(
    *, conversation_id: str, user_id: str, session: AsyncSession
) -> dict | None:
    """Return the conversation detail if it exists AND is owned by user_id."""
    try:
        pk = uuid.UUID(conversation_id)
    except ValueError:
        return None

    convo = await session.get(Conversation, pk)
    if convo is None or str(convo.user_id) != user_id:
        return None

    messages = await session.scalars(
        select(Message)
        .where(Message.conversation_id == convo.id)
        .order_by(Message.created_at.asc())
    )
    msg_rows = [
        {
            "role": m.role,
            "content": m.content,
            "citations": m.citations or [],
            "trace_id": m.trace_id,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]
    return {
        "id": str(convo.id),
        "title": convo.title,
        "created_at": convo.created_at.isoformat(),
        "message_count": len(msg_rows),
        "messages": msg_rows,
    }
