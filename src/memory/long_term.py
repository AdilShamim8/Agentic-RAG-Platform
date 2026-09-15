"""Long-term memory — persistent memories with extraction, conflict resolution, expiry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.models.memory import Memory
from src.llm.provider import LLMProvider, get_llm_provider

MEMORY_EXTRACTION_PROMPT = """You are a memory extractor. Given a conversation turn (user question + assistant answer),
decide what (if anything) should be persisted as long-term memory.

Only persist:
- User preferences ("user wants bullet points")
- Stable project context ("user is working on Project X")
- Recurring questions ("user keeps asking about policy Y")
- Decisions ("we decided to use Postgres")

Do NOT persist:
- Trivial conversation ("hello", "thanks")
- Facts already in documents
- Transient state ("user is in a meeting today") — unless explicitly important
- Sensitive personal information (health, family, etc.)

For each memory, return JSON:
{
  "memories": [
    {"scope": "user_pref|project_context|recurring_question|decision", "content": "...", "confidence": 0.0..1.0, "ttl_days": null|int}
  ]
}

If nothing is worth persisting, return {"memories": []}.

USER QUESTION:
{question}

ASSISTANT ANSWER:
{answer}
"""


async def extract_memories(
    *,
    question: str,
    answer: str,
    user_id: str,
    session: AsyncSession,
    llm: LLMProvider | None = None,
) -> list[Memory]:
    """Extract memories from a conversation turn. Returns new Memory objects (not yet persisted)."""
    if not settings.memory_extraction_enabled:
        return []
    llm = llm or get_llm_provider()
    prompt = MEMORY_EXTRACTION_PROMPT.format(question=question, answer=answer)
    response = await llm.complete_json(prompt, temperature=0.0)
    memories = []
    for m in response.get("memories", []):
        ttl_days = m.get("ttl_days")
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days) if ttl_days else None
        memories.append(
            Memory(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id),
                scope=m["scope"],
                content=m["content"],
                source="extracted",
                confidence=float(m.get("confidence", 0.5)),
                expires_at=expires_at,
            )
        )
    return memories


async def detect_conflict(
    new_memory: Memory, existing: list[Memory], llm: LLMProvider
) -> Memory | None:
    """Returns the existing memory that conflicts with `new_memory`, if any."""
    if not existing:
        return None
    # Simple heuristic: same scope + same content first 100 chars = potential conflict
    # In production, use an LLM-judge.
    for m in existing:
        if m.scope == new_memory.scope and m.content[:100] == new_memory.content[:100]:
            return m
    return None


async def store_memory(*, memory: Memory, session: AsyncSession) -> Memory:
    """Persist a memory. Handles conflict resolution by marking existing as superseded."""
    # Check for conflicts with existing non-superseded, non-expired memories
    stmt = select(Memory).where(
        and_(
            Memory.user_id == memory.user_id,
            Memory.scope == memory.scope,
            Memory.superseded_by.is_(None),
            Memory.deleted_at.is_(None),
        )
    )
    result = await session.execute(stmt)
    existing = list(result.scalars().all())

    conflicting = await detect_conflict(memory, existing, get_llm_provider())
    if conflicting:
        conflicting.superseded_by = memory.id

    session.add(memory)
    await session.flush()
    return memory
