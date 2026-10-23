"""Agent clarify + conflict-report behaviors, end to end against the DB.

Requires the fixture corpus (make seed + make seed-fixtures), including the
conflicting home-internet pair (IT: $40/month vs Finance: $60/month).
"""

from __future__ import annotations

import pytest

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from apps.api.app.services.query_service import AgentResult  # noqa: F401 (type ref)
from src.agents.conflict_detector import CONFLICT_ANSWER_PREFIX
from src.agents.generator import CLARIFICATION_ANSWER
from src.agents.orchestrator import run_agent


def _user() -> AuthUser:
    return AuthUser(
        id="03087f39-f7df-4bb9-a9cb-07cbd5a60db5",  # alice (seeded admin)
        email="alice@demo.dev",
        name="Alice Admin",
        role_slug="administrator",
        permissions=frozenset({"admin"}),
        projects=frozenset(),
        departments=frozenset(),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vague_query_gets_a_clarification_question() -> None:
    async with session_scope() as session:
        result = await run_agent(
            query="Tell me about the policy.",
            user=_user(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=5,
            trace_id="test-clarify",
        )
    assert result.answer == CLARIFICATION_ANSWER
    assert result.failure is None
    assert result.tool_call_count == 0  # no wasted retrieval on a vague query


@pytest.mark.integration
@pytest.mark.asyncio
async def test_conflicting_sources_are_reported_not_picked() -> None:
    async with session_scope() as session:
        result = await run_agent(
            query="What is the home internet reimbursement?",
            user=_user(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=5,
            trace_id="test-conflict",
        )
    assert result.answer.startswith(CONFLICT_ANSWER_PREFIX)
    assert result.failure is None
    # Both sides of the conflict are cited.
    doc_ids = {c.document_id for c in result.citations}
    assert "e0010000-0000-4000-8000-000000000013" in doc_ids  # IT: $40/month
    assert "e0010000-0000-4000-8000-000000000014" in doc_ids  # Finance: $60/month
    assert all(c.verified for c in result.citations)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unconflicted_query_still_answers_normally() -> None:
    """The conflict check must not break ordinary grounded answers."""
    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_user(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=5,
            trace_id="test-no-conflict",
        )
    assert not result.answer.startswith(CONFLICT_ANSWER_PREFIX)
    assert result.failure is None
    assert result.citations
