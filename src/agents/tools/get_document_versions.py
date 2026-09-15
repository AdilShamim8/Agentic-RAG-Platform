"""get_document_versions tool — list versions of a document."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.registry import ToolResult, register_tool


@register_tool(
    name="get_document_versions",
    description="List all versions of a document.",
    schema={
        "type": "object",
        "properties": {"document_id": {"type": "string"}},
        "required": ["document_id"],
    },
)
async def get_document_versions(
    *,
    sub_question: str,
    user: Any,
    session: AsyncSession,
    retrieval_strategy: str,
    top_k: int | None,
    document_id: str,
) -> ToolResult:
    """Return the version list as a synthetic chunk the LLM can read."""
    # TODO: query document_versions table
    return ToolResult(
        chunks=[], cost_usd=0.0, metadata={"document_id": document_id, "versions": []}
    )
