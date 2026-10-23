"""Memory service + memory_search tool tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from apps.api.app.main import app
from apps.api.app.models.audit import AuditLog
from apps.api.app.models.memory import Memory
from apps.api.app.models.user import User


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


async def _seed_memory(email: str, content: str, scope: str = "user_pref") -> str:
    async with session_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        m = Memory(
            id=uuid.uuid4(),
            user_id=user.id,
            scope=scope,
            content=content,
            source="test",
            confidence=0.9,
        )
        session.add(m)
        return str(m.id)


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with session_scope() as session:
        await session.execute(delete(Memory))
        await session.execute(delete(AuditLog).where(AuditLog.action.like("memory.%")))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_lifecycle() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        memory_id = await _seed_memory("alice@demo.dev", "User prefers bullet-point answers")

        # List
        listing = await client.get("/memory", headers={"Authorization": f"Bearer {alice}"})
        assert listing.status_code == 200
        assert any(m["id"] == memory_id for m in listing.json())

        # Update
        patched = await client.patch(
            f"/memory/{memory_id}",
            json={"content": "User prefers concise tables"},
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert patched.status_code == 200
        assert patched.json()["content"] == "User prefers concise tables"

        # Export
        export = await client.get("/memory/export", headers={"Authorization": f"Bearer {alice}"})
        assert export.status_code == 200
        body = export.json()
        assert body["count"] >= 1
        assert any(m["id"] == memory_id for m in body["memories"])

        # Delete
        deleted = await client.delete(
            f"/memory/{memory_id}", headers={"Authorization": f"Bearer {alice}"}
        )
        assert deleted.status_code == 200
        after = await client.get("/memory", headers={"Authorization": f"Bearer {alice}"})
        assert all(m["id"] != memory_id for m in after.json())

        # Audit rows for update + delete
        async with session_scope() as session:
            rows = await session.scalars(select(AuditLog).where(AuditLog.target == memory_id))
            actions = {r.action for r in rows}
        assert {"memory.update", "memory.delete"} <= actions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_isolation() -> None:
    """Carol cannot see, update, or delete Alice's memories."""
    memory_id = await _seed_memory("alice@demo.dev", "Alice likes dark mode")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        carol = await _login(client, "carol@demo.dev")

        listing = await client.get("/memory", headers={"Authorization": f"Bearer {carol}"})
        assert all(m["id"] != memory_id for m in listing.json())

        patched = await client.patch(
            f"/memory/{memory_id}",
            json={"content": "hijack"},
            headers={"Authorization": f"Bearer {carol}"},
        )
        assert patched.status_code == 404

        deleted = await client.delete(
            f"/memory/{memory_id}", headers={"Authorization": f"Bearer {carol}"}
        )
        assert deleted.status_code == 404

    # Alice's memory is untouched
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        listing = await client.get("/memory", headers={"Authorization": f"Bearer {alice}"})
        assert any(m["id"] == memory_id for m in listing.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_expired_and_deleted_memories_hidden() -> None:
    from datetime import UTC, datetime, timedelta

    memory_id = await _seed_memory("bob@demo.dev", "Bob works on Project X")
    async with session_scope() as session:
        m = await session.get(Memory, memory_id)
        m.expires_at = datetime.now(UTC) - timedelta(days=1)  # expired

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bob = await _login(client, "bob@demo.dev")
        listing = await client.get("/memory", headers={"Authorization": f"Bearer {bob}"})
        assert all(row["id"] != memory_id for row in listing.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_search_tool_scopes_to_owner() -> None:
    """The agent's memory_search tool must only return the caller's memories."""
    from src.agents.tools import execute_tool

    await _seed_memory("alice@demo.dev", "Alice prefers morning standups")
    await _seed_memory("bob@demo.dev", "Bob prefers morning standups")

    async with session_scope() as session:
        from sqlalchemy import select as sel

        alice_row = await session.scalar(sel(User).where(User.email == "alice@demo.dev"))
        user = AuthUser(
            id=str(alice_row.id),
            email=alice_row.email,
            name=alice_row.name,
            role_slug=alice_row.role_slug,
            permissions=frozenset(["read:document", "admin"]),
            projects=frozenset(),
            departments=frozenset(),
        )
        result = await execute_tool(
            tool_name="memory_search",
            args={},
            sub_question="standups",
            user=user,
            session=session,
            retrieval_strategy="hybrid_reranked",
            top_k=5,
        )
    contents = [c.content for c in result.chunks]
    assert contents, "expected at least one memory hit"
    assert all("Alice" in c for c in contents), "cross-user memory leak via memory_search"
