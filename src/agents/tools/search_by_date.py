"""search_by_date tool — retrieve chunks filtered by date range."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.registry import ToolResult, register_tool
from src.retrieval.engine import retrieve


@register_tool(
    name="search_by_date",
    description="Search chunks with a date filter (effective_from / effective_to).",
    schema={
        "type": "object",
        "properties": {
            "date_from": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
            "date_to": {"type": "string", "description": "ISO date (YYYY-MM-DD)"},
        },
        "required": [],
    },
)
async def search_by_date(
    *,
    sub_question: str,
    user: Any,
    session: AsyncSession,
    retrieval_strategy: str,
    top_k: int | None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> ToolResult:
    filters: dict[str, Any] = {}
    if date_from:
        filters["effective_from_gte"] = date.fromisoformat(date_from)
    if date_to:
        filters["effective_to_lte"] = date.fromisoformat(date_to)

    chunks = await retrieve(
        query=sub_question,
        user=user,
        session=session,
        strategy=retrieval_strategy,
        top_k=top_k or 10,
        candidate_count=50,
        filters=filters,
    )
    return ToolResult(chunks=chunks, cost_usd=0.0)
