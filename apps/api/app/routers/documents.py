"""Documents endpoints — ingest, list, get, delete, versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_current_user, require_permission
from apps.api.app.services.document_service import (
    get_document,
    get_document_versions,
    ingest_upload,
    list_documents,
    soft_delete_document,
)

router = APIRouter()


class DocumentOut(BaseModel):
    id: str
    title: str
    doc_type: str
    department: str | None
    owner_id: str | None
    version: int
    content_hash: str
    created_at: str
    updated_at: str


class DocumentDetail(DocumentOut):
    access_policy: dict
    effective_from: str | None
    effective_to: str | None
    source: str
    chunk_count: int


@router.get("", response_model=list[DocumentOut])
async def list_docs(
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 50,
    offset: int = 0,
) -> list[DocumentOut]:
    return await list_documents(user=user, session=session, limit=limit, offset=offset)


@router.post("/ingest", response_model=DocumentOut)
async def ingest(
    file: Annotated[UploadFile, File()],
    user: Annotated[AuthUser, Depends(require_permission("ingest"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    department: str = "general",
) -> DocumentOut:
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    return await ingest_upload(file=file, user=user, session=session, department=department)


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_doc(
    document_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetail:
    doc = await get_document(document_id=document_id, user=user, session=session)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{document_id}/versions")
async def get_versions(
    document_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    return await get_document_versions(document_id=document_id, user=user, session=session)


@router.delete("/{document_id}")
async def delete_doc(
    document_id: str,
    user: Annotated[AuthUser, Depends(require_permission("write:document"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    await soft_delete_document(document_id=document_id, user=user, session=session)
    return {"status": "deleted", "document_id": document_id}
