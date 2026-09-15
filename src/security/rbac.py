"""RBAC — role and permission resolution.

Roles: student, employee, manager, professor, administrator
Permissions: read:document, write:document, ingest, eval, admin
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    slug: str
    name: str
    permissions: frozenset[str]


ROLES: dict[str, Role] = {
    "student": Role(
        slug="student",
        name="Student",
        permissions=frozenset({"read:document"}),
    ),
    "employee": Role(
        slug="employee",
        name="Employee",
        permissions=frozenset({"read:document"}),
    ),
    "manager": Role(
        slug="manager",
        name="Manager",
        permissions=frozenset({"read:document", "write:document", "ingest"}),
    ),
    "professor": Role(
        slug="professor",
        name="Professor",
        permissions=frozenset({"read:document", "write:document", "ingest", "eval"}),
    ),
    "administrator": Role(
        slug="administrator",
        name="Administrator",
        permissions=frozenset({"read:document", "write:document", "ingest", "eval", "admin"}),
    ),
}


def get_role(slug: str) -> Role | None:
    return ROLES.get(slug)


def has_permission(role_slug: str, permission: str) -> bool:
    """True if the role grants the permission. Admin has everything."""
    role = get_role(role_slug)
    if role is None:
        return False
    return permission in role.permissions
