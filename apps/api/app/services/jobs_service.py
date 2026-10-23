"""Background job handlers (executed by scripts/worker.py).

Handlers reconstruct the acting user from the job payload (serialized by
the API at enqueue time), open their own DB session, and call the same
service layer the HTTP endpoints use - one pipeline, two entry points.

Handlers must be idempotent (at-least-once delivery): ingest dedupes by
content hash, so a redelivered job is a no-op returning the same document.
"""

from __future__ import annotations

import base64
import binascii
import logging

from pydantic import BaseModel, Field, ValidationError

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from apps.api.app.services.document_service import ingest_bytes

logger = logging.getLogger(__name__)


class IngestJobPayload(BaseModel):
    """Serialized form of an async ingest request."""

    filename: str = Field(min_length=1, max_length=255)
    content_b64: str = Field(min_length=4)  # base64 of the raw file bytes
    department: str = Field(default="general", max_length=64)
    user: dict  # AuthUser fields at enqueue time


def build_ingest_payload(*, filename: str, raw: bytes, user: AuthUser, department: str) -> dict:
    """Serialize an ingest request (producer side, in the API process)."""
    return IngestJobPayload(
        filename=filename,
        content_b64=base64.b64encode(raw).decode("ascii"),
        department=department or "general",
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role_slug": user.role_slug,
            "permissions": sorted(user.permissions),
            "projects": sorted(user.projects),
            "departments": sorted(user.departments),
        },
    ).model_dump()


def _payload_user(data: dict) -> AuthUser:
    u = data["user"]
    return AuthUser(
        id=u["id"],
        email=u.get("email", ""),
        name=u.get("name", ""),
        role_slug=u.get("role_slug", "employee"),
        permissions=frozenset(u.get("permissions", [])),
        projects=frozenset(u.get("projects", [])),
        departments=frozenset(u.get("departments", [])),
    )


class JobError(Exception):
    """Raised by handlers on permanent failures (recorded on the job)."""


async def run_ingest_job(payload: dict) -> dict:
    """Handle an 'ingest' job: decode, validate, run the ingest pipeline."""
    try:
        data = IngestJobPayload.model_validate(payload)
    except ValidationError as exc:
        # Malformed payloads will never succeed: fail permanently.
        raise JobError(f"invalid ingest payload: {exc}") from exc

    try:
        raw = base64.b64decode(data.content_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise JobError("payload is not valid base64") from exc

    user = _payload_user(data.model_dump())
    async with session_scope() as session:
        try:
            doc = await ingest_bytes(
                filename=data.filename,
                raw=raw,
                user=user,
                session=session,
                department=data.department,
            )
        except Exception as exc:
            # ingest_bytes raises HTTPException for user errors (bad type,
            # empty file, ...). Treat them as permanent job failures.
            detail = getattr(exc, "detail", str(exc))
            raise JobError(str(detail)) from exc
    logger.info("ingest job done: document=%s title=%r", doc.id, doc.title)
    return {"document_id": doc.id, "title": doc.title, "version": doc.version}
