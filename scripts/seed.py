"""Seed script — loads demo users, roles, departments, permissions."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from apps.api.app.core.db import session_scope
from apps.api.app.models.role import Permission, Role, role_permissions
from apps.api.app.models.user import User

ROLES = [
    {"slug": "student", "name": "Student"},
    {"slug": "employee", "name": "Employee"},
    {"slug": "manager", "name": "Manager"},
    {"slug": "professor", "name": "Professor"},
    {"slug": "administrator", "name": "Administrator"},
]

PERMISSIONS = [
    {"slug": "read:document", "name": "Read documents"},
    {"slug": "write:document", "name": "Write documents"},
    {"slug": "ingest", "name": "Ingest new documents"},
    {"slug": "eval", "name": "Run evaluations"},
    {"slug": "admin", "name": "Administrator access"},
]

ROLE_PERMISSIONS = {
    "student": ["read:document"],
    "employee": ["read:document"],
    "manager": ["read:document", "write:document", "ingest"],
    "professor": ["read:document", "write:document", "ingest", "eval"],
    "administrator": ["read:document", "write:document", "ingest", "eval", "admin"],
}

USERS = [
    {
        "email": "alice@demo.dev",
        "name": "Alice Admin",
        "password": "password123",
        "role": "administrator",
    },
    {"email": "bob@demo.dev", "name": "Bob Manager", "password": "password123", "role": "manager"},
    {
        "email": "carol@demo.dev",
        "name": "Carol Employee",
        "password": "password123",
        "role": "employee",
    },
    {
        "email": "dave@demo.dev",
        "name": "Dave Professor",
        "password": "password123",
        "role": "professor",
    },
    {"email": "eve@demo.dev", "name": "Eve Student", "password": "password123", "role": "student"},
]


async def seed() -> None:
    async with session_scope() as session:
        # Permissions
        perm_map: dict[str, Permission] = {}
        for p in PERMISSIONS:
            existing = await session.scalar(select(Permission).where(Permission.slug == p["slug"]))
            if existing is None:
                perm = Permission(id=uuid.uuid4(), name=p["name"], slug=p["slug"])
                session.add(perm)
                perm_map[p["slug"]] = perm
            else:
                perm_map[p["slug"]] = existing
        await session.flush()

        # Roles
        role_map: dict[str, Role] = {}
        for r in ROLES:
            existing = await session.scalar(select(Role).where(Role.slug == r["slug"]))
            if existing is None:
                role = Role(id=uuid.uuid4(), name=r["name"], slug=r["slug"])
                session.add(role)
                role_map[r["slug"]] = role
            else:
                role_map[r["slug"]] = existing
        await session.flush()

        # Role-permission links
        for role_slug, perm_slugs in ROLE_PERMISSIONS.items():
            role = role_map[role_slug]
            for perm_slug in perm_slugs:
                perm = perm_map[perm_slug]
                # Check if link exists
                link = await session.execute(
                    select(role_permissions).where(
                        role_permissions.c.role_id == role.id,
                        role_permissions.c.permission_id == perm.id,
                    )
                )
                if link.first() is None:
                    await session.execute(
                        role_permissions.insert().values(role_id=role.id, permission_id=perm.id)
                    )
        await session.flush()

        # Users
        for u in USERS:
            existing = await session.scalar(select(User).where(User.email == u["email"]))
            if existing is None:
                user = User(
                    id=uuid.uuid4(),
                    email=u["email"],
                    name=u["name"],
                    password_hash=User.hash_password(u["password"]),
                    role_slug=u["role"],
                )
                session.add(user)
        await session.commit()

    print("Seed complete. Users:")
    for u in USERS:
        print(f"  {u['email']} / {u['password']} ({u['role']})")


if __name__ == "__main__":
    asyncio.run(seed())
