"""Security tests for RBAC — real end-to-end retrieval checks against PostgreSQL.

These replace the previous empty `pass` stubs. Every test seeds actual
documents (with embeddings + FTS vectors), queries through the real
retrieval SQL (rag.access_matches), and asserts authorization outcomes.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, update

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from apps.api.app.main import app
from apps.api.app.models.document import Document
from src.retrieval.dense import dense_retrieve
from src.retrieval.engine import retrieve
from src.retrieval.hybrid import rrf_fuse
from src.retrieval.lexical import lexical_retrieve
from tests.helpers_seed import purge_docs, seed_doc


def _auth_user(role: str, user_id: str = "00000000-0000-0000-0000-000000000001") -> AuthUser:
    return AuthUser(
        id=user_id,
        email=f"{role}@demo.dev",
        name=role.title(),
        role_slug=role,
        permissions=frozenset(
            ["read:document"]
            if role in ("employee", "student")
            else ["read:document", "write:document", "ingest", "eval", "admin"]
        ),
        projects=frozenset(),
        departments=frozenset(),
    )


@pytest.mark.security
@pytest.mark.asyncio
async def test_employee_cannot_see_manager_only_chunk() -> None:
    """An employee querying manager-only info gets 0 such chunks; a manager does.

    The manager-only chunk is deliberately the MOST relevant chunk for the
    query, so if the SQL filter were applied after ranking it would leak.
    """
    seeded = await seed_doc(
        title="Project Alpha Budget",
        content="The budget for Project Alpha is $1.2 million for fiscal year 2025.",
        access_policy={"roles": ["manager", "administrator"]},
        department="finance",
    )
    try:
        query = "What is the budget for Project Alpha?"
        async with session_scope() as session:
            emp_user = _auth_user("employee")
            emp_dense = await dense_retrieve(query=query, user=emp_user, session=session, top_k=5)
            emp_lex = await lexical_retrieve(query=query, user=emp_user, session=session, top_k=5)
            emp_fused = rrf_fuse(emp_dense, emp_lex, top_n=5)

            mgr_user = _auth_user("manager")
            mgr_dense = await dense_retrieve(query=query, user=mgr_user, session=session, top_k=5)

        assert all(c.document_id != seeded.document_id for c in emp_dense), "dense leak"
        assert all(c.document_id != seeded.document_id for c in emp_lex), "lexical leak"
        assert all(c.document_id != seeded.document_id for c in emp_fused), "hybrid leak"
        assert any(
            c.document_id == seeded.document_id for c in mgr_dense
        ), "manager must see the chunk through dense retrieval"
    finally:
        await purge_docs(seeded.document_id)


@pytest.mark.security
@pytest.mark.asyncio
async def test_cross_user_no_leakage() -> None:
    """A user-allowlisted document is invisible to other non-admin users."""
    bob_id = "00000000-0000-0000-0000-00000000beef"  # synthetic; not a real user row
    seeded = await seed_doc(
        title="Bob Private Notes",
        content="Private onboarding notes for Bob only. Not for sharing.",
        access_policy={"users": [bob_id]},
    )
    try:
        async with session_scope() as session:
            # A different user id must get nothing from any strategy
            other = _auth_user("employee", user_id="00000000-0000-0000-0000-00000000abcd")
            for strategy in ("dense", "lexical", "hybrid"):
                chunks = await retrieve(
                    query="private onboarding notes",
                    user=other,
                    session=session,
                    strategy=strategy,
                    top_k=5,
                )
                assert all(
                    c.document_id != seeded.document_id for c in chunks
                ), f"leak via {strategy}"
            # The allowlisted user id sees it
            bob = _auth_user("employee", user_id=bob_id)
            chunks = await retrieve(
                query="private onboarding notes",
                user=bob,
                session=session,
                strategy="lexical",
                top_k=5,
            )
            assert any(c.document_id == seeded.document_id for c in chunks)
    finally:
        await purge_docs(seeded.document_id)


@pytest.mark.security
@pytest.mark.asyncio
async def test_role_escalation_blocked() -> None:
    """A request body claiming role=admin must not grant admin access.

    The role is derived from the authenticated user (JWT -> DB row), never
    from client-supplied values.
    """
    seeded = await seed_doc(
        title="Manager Only Doc",
        content="Secret strategy for next quarter: expand to EU market.",
        access_policy={"roles": ["manager", "administrator"]},
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login = await client.post(
                "/auth/login", json={"email": "carol@demo.dev", "password": "password123"}
            )
            assert login.status_code == 200
            token = login.json()["access_token"]

            # Body claims administrator role; the token says employee.
            response = await client.post(
                "/search",
                json={
                    "query": "secret strategy EU market",
                    "strategy": "hybrid",
                    "top_k": 10,
                    "filters": {"role": "administrator"},  # ignored server-side
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            results = response.json()["results"]
            assert all(
                r["document_id"] != seeded.document_id for r in results
            ), "role escalation via request body leaked a restricted document"

            # Admin-only endpoint must 403 for carol
            admin = await client.get("/admin/stats", headers={"Authorization": f"Bearer {token}"})
            assert admin.status_code == 403

            # And alice (real administrator) does see the doc via /search
            login_alice = await client.post(
                "/auth/login", json={"email": "alice@demo.dev", "password": "password123"}
            )
            token_alice = login_alice.json()["access_token"]
            as_alice = await client.post(
                "/search",
                json={"query": "secret strategy EU market", "strategy": "hybrid", "top_k": 10},
                headers={"Authorization": f"Bearer {token_alice}"},
            )
            assert any(r["document_id"] == seeded.document_id for r in as_alice.json()["results"])
    finally:
        await purge_docs(seeded.document_id)


@pytest.mark.security
@pytest.mark.asyncio
async def test_deleted_document_excluded() -> None:
    """Soft-deleted documents must never be retrievable."""
    seeded = await seed_doc(
        title="To Be Deleted",
        content="Temporary memo about office relocation plans.",
    )
    try:
        async with session_scope() as session:
            await session.execute(
                update(Document)
                .where(Document.id == seeded.document_id)
                .values(deleted_at=func.now())
            )

        user = _auth_user("employee")
        async with session_scope() as session:
            for strategy in ("dense", "lexical"):
                chunks = await retrieve(
                    query="office relocation plans",
                    user=user,
                    session=session,
                    strategy=strategy,
                    top_k=5,
                )
                assert all(c.document_id != seeded.document_id for c in chunks)
    finally:
        await purge_docs(seeded.document_id)
