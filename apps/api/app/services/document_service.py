"""Document service — ingest, list, get, delete."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.deps.auth import AuthUser
from apps.api.app.routers.documents import DocumentOut


async def list_documents(
    *, user: AuthUser, session: AsyncSession, limit: int, offset: int
) -> list[DocumentOut]:
    """List documents the user is authorized to see."""
    # TODO: implement with access_matches filter
    return []


async def ingest_upload(
    *, file: UploadFile, user: AuthUser, session: AsyncSession, department: str
) -> DocumentOut:
    """Ingest an uploaded file."""
    # TODO: implement — call src.ingestion.pipeline
    raise NotImplementedError


async def get_document(*, document_id: str, user: AuthUser, session: AsyncSession) -> Any:
    """Get a single document."""
    # TODO: implement
    return None


async def get_document_versions(
    *, document_id: str, user: AuthUser, session: AsyncSession
) -> list[dict]:
    """Get all versions of a document."""
    # TODO: implement
    return []


async def soft_delete_document(*, document_id: str, user: AuthUser, session: AsyncSession) -> None:
    """Soft-delete a document (sets deleted_at)."""
    # TODO: implement + write audit log
    pass
