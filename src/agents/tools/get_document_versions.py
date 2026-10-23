"""get_document_versions tool — list versions of a document.

Previously returned a TODO stub with empty versions. Now queries the
document_versions table with the same authorization rule as the document
APIs (403-equivalent PermissionError for foreign documents) and surfaces
the history as a synthetic evidence chunk the planner can reason over.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.registry import ToolResult, register_tool
from src.retrieval.types import ScoredChunk


@register_tool(
    name="get_document_versions",
    description="List all versions of a document.",
    schema={
        "type": "object",
        "properties": {
            "document_id": {"type": "string", "minLength": 1}
        },
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
    import uuid as _uuid

    from apps.api.app.models.document import Document, DocumentVersion
    from src.security.access import can_access

    try:
        pk = _uuid.UUID(document_id)
    except ValueError as exc:
        raise ValueError(f"document_id is not a valid UUID: {document_id}") from exc

    doc = await session.get(Document, pk)
    if doc is None or doc.deleted_at is not None:
        raise ValueError(f"Document not found: {document_id}")
    if not can_access(
        user_role=user.role_slug,
        user_projects=user.projects,
        user_id=user.id,
        access_policy=doc.access_policy or {},
    ):
        raise PermissionError(f"Not authorized for document {document_id}")

    rows = await session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version.desc())
    )
    versions = [
        {
            "version": v.version,
            "content_hash": v.content_hash,
            "change_summary": v.change_summary,
            "created_at": v.created_at.isoformat(),
        }
        for v in rows
    ]
    lines = [
        f"Document '{doc.title}' (id={doc.id}) has {len(versions)} version(s):"
    ]
    for v in versions:
        summary = v["change_summary"] or "no summary"
        lines.append(f"- v{v['version']} created {v['created_at']}: {summary}")

    chunk = ScoredChunk(
        chunk_id=f"versions-{doc.id}",
        document_id=str(doc.id),
        document_title=doc.title,
        content="\n".join(lines),
        score=1.0,
        page=None,
        section="versions",
        url=None,
        version=doc.version,
    )
    return ToolResult(chunks=[chunk], cost_usd=0.0,
                      metadata={"document_id": str(doc.id), "versions": versions})
