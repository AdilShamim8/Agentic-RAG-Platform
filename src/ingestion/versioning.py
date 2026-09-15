"""Versioning — content-hash based change detection."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.document import Document, DocumentVersion


async def detect_change(
    *, content_hash: str, document: Document, session: AsyncSession
) -> tuple[bool, int]:
    """Returns (has_changed, new_version_number)."""
    if document.content_hash == content_hash:
        return False, document.version
    return True, document.version + 1


async def create_version_record(
    *,
    document_id,
    version: int,
    content_hash: str,
    change_summary: str | None,
    created_by,
    session: AsyncSession,
) -> DocumentVersion:
    """Create a new version record and mark old versions as superseded."""
    # Mark existing latest version as superseded by the new one
    # (in production, do this in a transaction)
    new_version = DocumentVersion(
        document_id=document_id,
        version=version,
        content_hash=content_hash,
        change_summary=change_summary,
        created_by=created_by,
    )
    session.add(new_version)
    await session.flush()
    return new_version
