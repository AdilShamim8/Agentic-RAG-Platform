"""Documents endpoints — ingest (sync + async), list, get, delete, versions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core import jobs
from apps.api.app.core.db import get_session
from apps.api.app.deps.auth import AuthUser, get_auth_user, require_permission
from apps.api.app.schemas import DocumentDetail, DocumentOut

router = APIRouter()


from apps.api.app.services.document_service import (  # noqa: E402
    get_document,
    get_document_versions,
    ingest_upload,
    list_documents,
    soft_delete_document,
)
from apps.api.app.services.jobs_service import build_ingest_payload  # noqa: E402


@router.get("", response_model=list[DocumentOut])
async def list_docs(
    user: Annotated[AuthUser, Depends(get_auth_user)],
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


@router.post("/ingest-async", status_code=202, summary="Queue an ingest job")
async def ingest_async(
    file: Annotated[UploadFile, File()],
    user: Annotated[AuthUser, Depends(require_permission("ingest"))],
    department: str = "general",
) -> dict:
    """Validate the upload, queue it for the background worker, return 202.

    Same validation as the sync path (extension, size, magic bytes) - only
    the parsing/embedding work is deferred. Poll GET /documents/jobs/{id}.
    """
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    raw = await file.read()

    from apps.api.app.services.document_service import (  # local: avoid cycle risk
        ALLOWED_EXTENSIONS,
        MAX_UPLOAD_BYTES,
        _magic_matches,
    )

    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
        )
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400, detail=f"Unsupported file type .{ext}; allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )
    content_type = "html" if ext == "htm" else ext
    if not _magic_matches(content_type, raw):
        raise HTTPException(400, "File content does not match its extension")

    payload = build_ingest_payload(
        filename=file.filename, raw=raw, user=user, department=department
    )
    try:
        client = await jobs.get_jobs_client()
        job_id = await jobs.enqueue(client, kind="ingest", payload=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Job queue unavailable; use the synchronous /ingest endpoint",
        ) from exc
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}", summary="Ingest job status")
async def ingest_job_status(
    job_id: str,
    user: Annotated[AuthUser, Depends(get_auth_user)],
) -> dict:
    """Poll a queued ingest job. Only the owner (or an admin) may read it."""
    try:
        client = await jobs.get_jobs_client()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Job queue unavailable") from exc
    job = await jobs.get_job(client, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    owner_id = (job.get("payload") or {}).get("user", {}).get("id")
    if owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Not your job")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
        "enqueued_at": job.get("enqueued_at"),
        "finished_at": job.get("finished_at"),
    }


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_doc(
    document_id: str,
    user: Annotated[AuthUser, Depends(get_auth_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentDetail:
    doc = await get_document(document_id=document_id, user=user, session=session)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{document_id}/versions")
async def get_versions(
    document_id: str,
    user: Annotated[AuthUser, Depends(get_auth_user)],
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
