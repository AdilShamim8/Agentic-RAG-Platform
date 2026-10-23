"""Auth dependencies — current user extraction + permission checks.

Two layers:
- `routers.auth.get_current_user` resolves the JWT to the ORM `User` (auth endpoints).
- `get_auth_user` (below) converts it to a lightweight `AuthUser` value object.

Routers and services MUST depend on `get_auth_user`: passing the ORM `User`
into services/agents breaks attribute contracts (`User.permissions` is an
async property -> coroutine, `User.projects` is not a frozenset), which
previously caused "coroutine was never awaited" warnings and made tool
permission checks meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status

from apps.api.app.models.user import User
from apps.api.app.routers.auth import get_current_user


@dataclass(slots=True)
class AuthUser:
    """Lightweight auth user object passed to services and the agent."""

    id: str
    email: str
    name: str
    role_slug: str
    permissions: frozenset[str]
    projects: frozenset[str]
    departments: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role_slug == "administrator"

    def has_permission(self, perm: str) -> bool:
        return perm in self.permissions or "admin" in self.permissions


async def to_auth_user(user: User) -> AuthUser:
    """Convert an ORM User to an AuthUser value object."""
    return AuthUser(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role_slug=user.role_slug,
        permissions=frozenset([p.slug for p in (await user.permissions)]),
        projects=frozenset([str(p.id) for p in (await user.projects)]),
        departments=frozenset([d.slug for d in (await user.departments)]),
    )


async def get_auth_user(
    current: Annotated[User, Depends(get_current_user)],
) -> AuthUser:
    """Dependency used by all non-auth routers. Always yields AuthUser."""
    return await to_auth_user(current)


def require_permission(*perms: str):
    """Returns a dependency that asserts the user has at least one of the given permissions."""

    async def _checker(user: Annotated[AuthUser, Depends(get_auth_user)]) -> AuthUser:
        if not any(user.has_permission(p) for p in perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {perms}",
            )
        return user

    return _checker
