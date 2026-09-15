"""Security tests for RBAC."""

from __future__ import annotations

import pytest


@pytest.mark.security
@pytest.mark.asyncio
async def test_employee_cannot_see_manager_only_chunk():
    """An employee querying for manager-only info should get 0 results."""
    # TODO: seed a manager-only document, query as employee, assert no chunks returned
    pass


@pytest.mark.security
@pytest.mark.asyncio
async def test_cross_user_no_leakage():
    """User A's private documents should not be retrievable by user B."""
    # TODO: ingest as user A, query as user B, assert no results
    pass


@pytest.mark.security
@pytest.mark.asyncio
async def test_no_indirect_leakage_via_citation():
    """Citation links to unauthorized chunks must be broken."""
    # TODO: manually craft a citation to an unauthorized chunk, assert the citation is dropped
    pass


@pytest.mark.security
@pytest.mark.asyncio
async def test_role_escalation_blocked():
    """Supplying role=admin in the request body must not grant admin."""
    # The role is read from the JWT, never from the request body.
    # TODO: send a request with role:admin in body but an employee JWT, assert no admin access
    pass
