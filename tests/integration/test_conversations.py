"""Conversations + message persistence tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core.db import session_scope
from apps.api.app.main import app
from apps.api.app.models.conversation import Conversation, Message
from tests.helpers_seed import purge_docs, seed_doc

MARKDOWN = b"""# Remote Work Policy

Employees may work remotely up to 3 days per week under the current policy.
"""


async def _login(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    # Remove conversations/messages created by these tests (owned by seeded users)
    async with session_scope() as session:
        from sqlalchemy import delete

        await session.execute(delete(Message))
        await session.execute(delete(Conversation))


@pytest.fixture()
async def policy_doc():
    seeded = await seed_doc(
        title="Remote Work Policy",
        content="Employees may work remotely up to 3 days per week under the current policy.",
    )
    try:
        yield seeded
    finally:
        await purge_docs(seeded.document_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_persists_messages(policy_doc) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")

        first = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert first.status_code == 200
        convo_id = first.json()["conversation_id"]
        assert first.json()["failure"] is None

        # Second turn reuses the SAME conversation id
        second = await client.post(
            "/query",
            json={
                "query": "And how many days exactly?",
                "conversation_id": convo_id,
            },
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert second.status_code == 200
        assert second.json()["conversation_id"] == convo_id

    # The conversation now contains 4 messages (2 turns x user+assistant)
    detail = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        detail = await client.get(
            f"/conversations/{convo_id}", headers={"Authorization": f"Bearer {alice}"}
        )
    assert detail.status_code == 200
    body = detail.json()
    assert body["message_count"] == 4
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert body["messages"][1]["trace_id"] == first.json()["trace_id"]
    assert body["messages"][1]["citations"], "assistant turn must persist citations"
    assert body["messages"][1]["citations"][0]["verified"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_listing_and_create(policy_doc) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        created = await client.post(
            "/conversations",
            params={"title": "My thread"},
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert created.status_code == 200
        convo_id = created.json()["id"]

        listing = await client.get("/conversations", headers={"Authorization": f"Bearer {alice}"})
        assert any(c["id"] == convo_id for c in listing.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conversation_idor_blocked(policy_doc) -> None:
    """Another user's conversation id must return 404 and never leak content."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        alice = await _login(client, "alice@demo.dev")
        bob = await _login(client, "bob@demo.dev")

        first = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {alice}"},
        )
        convo_id = first.json()["conversation_id"]

        # Bob cannot read Alice's conversation
        foreign = await client.get(
            f"/conversations/{convo_id}", headers={"Authorization": f"Bearer {bob}"}
        )
        assert foreign.status_code == 404

        # Bob cannot write into it either: /query with a foreign conversation_id
        # must NOT append to Alice's thread (it creates a new one for Bob)
        bob_turn = await client.post(
            "/query",
            json={"query": "What is our remote work policy?", "conversation_id": convo_id},
            headers={"Authorization": f"Bearer {bob}"},
        )
        assert bob_turn.status_code == 200
        assert bob_turn.json()["conversation_id"] != convo_id

        # And Alice's thread still has exactly her 2 messages
        alice_view = await client.get(
            f"/conversations/{convo_id}", headers={"Authorization": f"Bearer {alice}"}
        )
        assert alice_view.json()["message_count"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_query_still_persists(policy_doc) -> None:
    """Even a failed agent run records both turns with the failure metadata."""

    from sqlalchemy import select

    from apps.api.app.core.db import session_scope
    from apps.api.app.deps.auth import AuthUser
    from apps.api.app.models.user import User
    from apps.api.app.services.query_service import run_agentic_query

    async with session_scope() as session:
        alice_row = await session.scalar(select(User).where(User.email == "alice@demo.dev"))
    user = AuthUser(
        id=str(alice_row.id),
        email=alice_row.email,
        name=alice_row.name,
        role_slug=alice_row.role_slug,
        permissions=frozenset(["read:document", "admin"]),
        projects=frozenset(),
        departments=frozenset(),
    )
    async with session_scope() as session:
        response = await run_agentic_query(
            query="zzz unmatched gibberish token xyzzy",
            user=user,
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="trace-failed-persist",
        )
    assert response.conversation_id
    async with session_scope() as session:
        from sqlalchemy import select

        msgs = await session.scalars(
            select(Message).where(Message.conversation_id == response.conversation_id)
        )
        rows = list(msgs)
    assert len(rows) == 2
    assistant = next(m for m in rows if m.role == "assistant")
    assert assistant.trace_id == "trace-failed-persist"
    assert assistant.metadata_["failure"] is not None or assistant.metadata_["confidence"]
