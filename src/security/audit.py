"""Audit logging — append-only log of privileged actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models.audit import AuditLog


async def log_action(
    *,
    session: AsyncSession,
    actor_id: str | None,
    action: str,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> None:
    """Append an entry to the audit log. Never raises."""
    try:
        entry = AuditLog(
            id=uuid.uuid4(),
            actor_id=uuid.UUID(actor_id) if actor_id else None,
            action=action,
            target=target,
            metadata_=metadata or {},
            trace_id=trace_id,
            created_at=datetime.now(UTC),
        )
        session.add(entry)
        await session.flush()
    except Exception:
        # Audit log failures must NOT crash the request.
        # In production: log to stderr + send to a dead-letter queue.
        pass
