"""memory_search tool — search the user's long-term memory."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.registry import ToolResult, register_tool
from src.memory.retrieval import search_memories


@register_tool(
    name="memory_search",
    description="Search the user's long-term memory.",
    schema={"type": "object", "properties": {}, "required": []},
)
async def memory_search(
    *,
    sub_question: str,
    user: Any,
    session: AsyncSession,
    retrieval_strategy: str,
    top_k: int | None,
) -> ToolResult:
    """Retrieve the user's persistent memories relevant to sub_question."""
    memories = await search_memories(
        query=sub_question, user_id=user.id, session=session, top_k=top_k or 5
    )
    # Convert memories to ScoredChunk-like objects so the rest of the pipeline can use them uniformly
    from src.retrieval.types import ScoredChunk

    chunks = [
        ScoredChunk(
            chunk_id=f"memory-{m.id}",
            document_id="memory",
            document_title="User memory",
            content=m.content,
            score=m.confidence,
            page=None,
            section=None,
            url=None,
            version=1,
            effective_from=None,
            effective_to=None,
        )
        for m in memories
    ]
    return ToolResult(chunks=chunks, cost_usd=0.0)
