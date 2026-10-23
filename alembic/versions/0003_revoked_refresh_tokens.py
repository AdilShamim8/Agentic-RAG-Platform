"""add revoked_refresh_tokens (refresh-token revocation list)

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-03 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_refresh_tokens",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_revoked_refresh_tokens_expires_at", "revoked_refresh_tokens", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_refresh_tokens_expires_at", table_name="revoked_refresh_tokens")
    op.drop_table("revoked_refresh_tokens")
