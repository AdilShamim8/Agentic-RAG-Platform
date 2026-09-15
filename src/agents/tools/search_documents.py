"""search_documents tool — the primary retrieval tool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.registry import ToolResult, register_tool
from src.retrieval.engine import retrieve


@register_tool(
    name="search_documents",
    description="Search the document corpus by semantic + lexical match.",
    schema={
        "type": "object",
        "properties": {
            "department": {"type": "string", "description": "Filter by department slug"},
            "document_type": {"type": "string", "description": "Filter by document type"},
        },
        "required": [],
    },
)
async def search_documents(
    *,
    sub_question: str,
    user: Any,
    session: AsyncSession,
    retrieval_strategy: str,
    top_k: int | None,
    department: str | None = None,
    document_type: str | None = None,
) -> ToolResult:
    """Search documents matching the sub_question."""
    filters: dict[str, Any] = {}
    if department:
        filters["department"] = department
    if document_type:
        filters["doc_type"] = document_type

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
