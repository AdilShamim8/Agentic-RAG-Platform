"""User ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.core.db import Base
from apps.api.app.models.role import Permission

# Compatibility shim for passlib with bcrypt >= 4.1.0
try:
    import bcrypt

    if not hasattr(bcrypt, "__about__"):

        class _BcryptAbout:
            __version__ = getattr(bcrypt, "__version__", "4.0.1")

        bcrypt.__about__ = _BcryptAbout()  # type: ignore
except ImportError:
    pass

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "student": ["read:document"],
    "employee": ["read:document"],
    "manager": ["read:document", "write:document", "ingest"],
    "professor": ["read:document", "write:document", "ingest", "eval"],
    "administrator": ["read:document", "write:document", "ingest", "eval", "admin"],
}


class User(Base):
    """User model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_slug: Mapped[str] = mapped_column(String(64), nullable=False, default="employee")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def hash_password(cls, password: str) -> str:
        """Hash a plain text password."""
        return pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return pwd_context.verify(password, self.password_hash)

    @property
    async def permissions(self) -> list[Permission]:
        """User permissions based on role."""
        slugs = ROLE_PERMISSIONS.get(self.role_slug, ["read:document"])
        return [Permission(id=uuid.uuid4(), name=s, slug=s) for s in slugs]

    @property
    async def projects(self) -> list:
        """User project memberships."""
        return []

    @property
    async def departments(self) -> list:
        """User department memberships."""
        return []
