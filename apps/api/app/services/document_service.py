"""Document service — ingest, list, get, versions, soft delete.

Implements the documented lifecycle that previously consisted of TODO
stubs (empty lists, NotImplementedError, silent pass-through):
- ingest: extension whitelist + magic-byte sniffing + size cap, parse,
  clean, chunk (configured strategy), embed + index, version record,
  audit log; duplicate uploads (same content hash) are idempotent
- list/get/versions/delete: authorization checked server-side on every
  path (rag.access_matches in the list SQL; can_access on PK lookups)
- delete is a soft delete (deleted_at) + audit log; retrieval SQL already
  excludes soft-deleted documents
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import settings
from apps.api.app.deps.auth import AuthUser
from apps.api.app.models.audit import AuditLog
from apps.api.app.models.document import Document, DocumentChunk, DocumentVersion, Source
from apps.api.app.schemas import DocumentDetail, DocumentOut
from src.ingestion.chunking import get_chunker
from src.ingestion.cleaning import clean
from src.ingestion.fetchers import RawDocument
from src.ingestion.indexer import index_chunks
from src.ingestion.metadata import content_hash, extract_title
from src.ingestion.parsers import get_parser
from src.ingestion.versioning import create_version_record
from src.security.access import can_access

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {"md", "txt", "pdf", "docx", "html", "htm"}


def _magic_matches(content_type: str, content: bytes) -> bool:
    """Best-effort content sniffing (extension lies are rejected)."""
    if content_type == "pdf":
        return content.startswith(b"%PDF")
    if content_type == "docx":
        return content.startswith(b"PK\x03\x04") or content.startswith(b"PK\x05\x06")
    if content_type in ("html", "htm"):
        head = content[:2048].lower()
        return b"<html" in head or b"<!doctype html" in head
    # md/txt: any bytes; decoded with replacement downstream
    return True


def _authorized(user: AuthUser, doc: Document) -> bool:
    return can_access(
        user_role=user.role_slug,
        user_projects=user.projects,
        user_id=user.id,
        access_policy=doc.access_policy or {},
    )


async def _get_authorized_or_raise(
    document_id: str, user: AuthUser, session: AsyncSession
) -> Document:
    try:
        pk = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc

    doc = await session.get(Document, pk)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _authorized(user, doc):
        raise HTTPException(status_code=403, detail="Not authorized for this document")
    return doc


async def list_documents(
    *, user: AuthUser, session: AsyncSession, limit: int, offset: int
) -> list[DocumentOut]:
    """List documents the user is authorized to see (RBAC in the SQL WHERE)."""
    sql = text("""
        SELECT d.id, d.title, d.doc_type, d.department, d.owner_id, d.version,
               d.content_hash, d.created_at, d.updated_at
        FROM documents d
        WHERE d.deleted_at IS NULL
          AND rag.access_matches(d.access_policy, :user_role, :user_projects, :user_id)
        ORDER BY d.created_at DESC
        LIMIT :limit OFFSET :offset
        """)
    result = await session.execute(
        sql,
        {
            "user_role": user.role_slug,
            "user_projects": list(user.projects),
            "user_id": user.id,
            "limit": limit,
            "offset": offset,
        },
    )
    out: list[DocumentOut] = []
    for r in result.mappings():
        out.append(
            DocumentOut(
                id=str(r["id"]),
                title=r["title"],
                doc_type=r["doc_type"],
                department=r["department"],
                owner_id=str(r["owner_id"]) if r["owner_id"] else None,
                version=r["version"],
                content_hash=r["content_hash"],
                created_at=r["created_at"].isoformat(),
                updated_at=r["updated_at"].isoformat(),
            )
        )
    return out


async def ingest_upload(
    *, file: UploadFile, user: AuthUser, session: AsyncSession, department: str
) -> DocumentOut:
    """Ingest an uploaded file: validate -> parse -> clean -> chunk -> index -> version + audit."""
    raw = await file.read()
    filename = file.filename or "upload"

    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"
        )

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type .{ext}; allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    content_type = "html" if ext == "htm" else ext
    if not _magic_matches(content_type, raw):
        raise HTTPException(status_code=400, detail="File content does not match its extension")

    raw_doc = RawDocument(
        source="upload",
        path_or_url=filename,
        content=raw,
        content_type=content_type,
        metadata={"filename": filename},
    )
    parsed = get_parser(content_type).parse(raw_doc)
    body = clean(parsed.markdown_text or "")
    if not body.strip():
        raise HTTPException(status_code=400, detail="No extractable text in file")
    parsed.markdown_text = body

    chunker = get_chunker(settings.ingestion_chunk_strategy)
    chunks = chunker.chunk(parsed)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document produced no chunks")

    digest = content_hash(body)
    title = extract_title(parsed, raw_doc)[:255]

    # Idempotent duplicate handling: same content -> same document
    existing = await session.scalar(
        select(Document)
        .where(Document.content_hash == digest, Document.deleted_at.is_(None))
        .limit(1)
    )
    if existing is not None:
        return _to_out(existing)

    doc = Document(
        id=uuid.uuid4(),
        title=title,
        doc_type=content_type,
        department=department or "general",
        owner_id=uuid.UUID(user.id),
        access_policy={},
        content_hash=digest,
        version=1,
    )
    session.add(doc)
    await session.flush()

    inserted = await index_chunks(document=doc, chunks=chunks, session=session)
    if inserted == 0:
        raise HTTPException(status_code=500, detail="Indexing produced no chunks")

    await create_version_record(
        document_id=doc.id,
        version=1,
        content_hash=digest,
        change_summary="initial ingest",
        created_by=uuid.UUID(user.id),
        session=session,
    )

    session.add(
        AuditLog(
            actor_id=uuid.UUID(user.id),
            action="document.ingest",
            target=str(doc.id),
            metadata_={"title": title, "chunks": inserted, "department": department},
        )
    )
    return _to_out(doc)


async def get_document(
    *, document_id: str, user: AuthUser, session: AsyncSession
) -> DocumentDetail | None:
    doc = await _get_authorized_or_raise(document_id, user, session)

    chunk_count = await session.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    )
    source_name = "upload"
    if doc.source_id is not None:
        src = await session.get(Source, doc.source_id)
        source_name = src.name if src is not None else "unknown"

    return DocumentDetail(
        id=str(doc.id),
        title=doc.title,
        doc_type=doc.doc_type,
        department=doc.department,
        owner_id=str(doc.owner_id) if doc.owner_id else None,
        version=doc.version,
        content_hash=doc.content_hash,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
        access_policy=doc.access_policy or {},
        effective_from=doc.effective_from.isoformat() if doc.effective_from else None,
        effective_to=doc.effective_to.isoformat() if doc.effective_to else None,
        source=source_name,
        chunk_count=int(chunk_count or 0),
    )


async def get_document_versions(
    *, document_id: str, user: AuthUser, session: AsyncSession
) -> list[dict]:
    doc = await _get_authorized_or_raise(document_id, user, session)
    rows = await session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version.desc())
    )
    return [
        {
            "version": v.version,
            "content_hash": v.content_hash,
            "change_summary": v.change_summary,
            "created_at": v.created_at.isoformat(),
            "created_by": str(v.created_by) if v.created_by else None,
            "superseded_by": str(v.superseded_by) if v.superseded_by else None,
        }
        for v in rows
    ]


async def soft_delete_document(*, document_id: str, user: AuthUser, session: AsyncSession) -> None:
    """Soft-delete (deleted_at) + audit log. Chunks stay for history; retrieval excludes deleted docs."""
    doc = await _get_authorized_or_raise(document_id, user, session)
    doc.deleted_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_id=uuid.UUID(user.id),
            action="document.delete",
            target=str(doc.id),
            metadata_={"title": doc.title},
        )
    )
    await session.flush()


def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=str(doc.id),
        title=doc.title,
        doc_type=doc.doc_type,
        department=doc.department,
        owner_id=str(doc.owner_id) if doc.owner_id else None,
        version=doc.version,
        content_hash=doc.content_hash,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )
