"""Revoked refresh tokens (the refresh-token revocation list).

Refresh tokens carry a unique ``jti`` claim. When a token is rotated or a
user logs out, its ``jti`` is recorded here; ``/auth/refresh`` rejects any
token whose ``jti`` appears in this table (reuse detection). Rows are pruned
once the underlying token's ``exp`` has passed - the table is only ever a
*deny list*, never a source of truth for validity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.db import Base


class RevokedRefreshToken(Base):
    """A revoked (rotated or logged-out) refresh token, by JWT ID."""

    __tablename__ = "revoked_refresh_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The underlying JWT's exp - after this instant the row is redundant.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
