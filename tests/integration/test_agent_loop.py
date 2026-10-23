"""Agent loop integration tests: bounded re-planning, step-failure tolerance,
budget enforcement, and the full happy path through the real stack
(mock LLM + deterministic test embedder/reranker + real PostgreSQL +
real rag.access_matches authorization).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core.db import session_scope
from apps.api.app.deps.auth import AuthUser
from apps.api.app.main import app
from src.agents.orchestrator import run_agent
from src.llm.provider import _MockLLMProvider
from tests.helpers_seed import purge_docs, seed_doc


class ScriptedLLM(_MockLLMProvider):
    """Mock LLM with per-prompt-kind scripted responses (falls back to defaults)."""

    def __init__(self, script: dict[str, list] | None = None) -> None:
        super().__init__()
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.seen_prompts: list[str] = []

    async def complete_json(self, prompt: str, *, temperature: float = 0.0) -> dict:
        self.seen_prompts.append(prompt)
        pl = prompt.lower()
        if "planner" in pl:
            kind = "planner"
        elif "evidence sufficiency" in pl:
            kind = "sufficiency"
        elif "query classifier" in pl:
            kind = "classifier"
        else:
            kind = "other"
        queue = self.script.get(kind)
        if queue:
            item = queue.pop(0)
            if item is None:
                return await super().complete_json(prompt, temperature=temperature)
            if isinstance(item, Exception):
                raise item
            return item
        return await super().complete_json(prompt, temperature=temperature)


def _employee(user_id: str = "00000000-0000-0000-0000-000000000001") -> AuthUser:
    return AuthUser(
        id=user_id,
        email="employee@demo.dev",
        name="Employee",
        role_slug="employee",
        permissions=frozenset(["read:document"]),
        projects=frozenset(),
        departments=frozenset(),
    )


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
async def test_happy_path_full_stack(policy_doc, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: /query returns a grounded, cited answer with no failure."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post(
            "/auth/login", json={"email": "alice@demo.dev", "password": "password123"}
        )
        token = login.json()["access_token"]
        response = await client.post(
            "/query",
            json={"query": "What is our remote work policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["failure"] is None, f"unexpected failure: {body['failure']}"
    assert "3 days" in body["answer"]
    assert body["citations"], "expected at least one citation"
    assert body["citations"][0]["verified"] is True
    assert body["citations"][0]["document_id"] == policy_doc.document_id
    assert body["metadata"]["replans"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replan_used_when_evidence_insufficient(
    policy_doc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First sufficiency check fails, second passes -> the agent re-plans and answers."""
    llm = ScriptedLLM(
        script={
            "sufficiency": [
                {"sufficient": False, "reason": "not enough"},
                {"sufficient": True, "reason": "second attempt found it"},
            ]
        }
    )
    monkeypatch.setattr("src.agents.orchestrator.get_llm_provider", lambda: llm)

    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-replan",
        )

    assert result.failure is None
    assert result.replans == 1
    # Two planning rounds (initial + replan), each producing a planner prompt
    planner_prompts = [p for p in llm.seen_prompts if "planner" in p.lower()]
    assert len(planner_prompts) >= 2, "expected a re-planning round"
    # The replan planner prompt must carry the feedback block
    assert any("FEEDBACK" in p for p in planner_prompts), "replan prompt lacks feedback"
    assert "3 days" in result.answer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replan_exhaustion_abstains(policy_doc, monkeypatch: pytest.MonkeyPatch) -> None:
    """Evidence never becomes sufficient -> bounded attempts, honest abstention."""
    llm = ScriptedLLM(script={"sufficiency": [{"sufficient": False, "reason": "no"}] * 10})
    monkeypatch.setattr("src.agents.orchestrator.get_llm_provider", lambda: llm)

    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-exhaust",
        )

    assert result.failure == "insufficient_evidence"
    assert result.answer == "I don't have enough evidence to answer this confidently."
    # Bounded: at most max_replans+1 evidence rounds, each with <=4 steps
    assert result.tool_call_count <= 10
    assert result.replans == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unrelated_document_abstains(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query with no matching corpus returns the honest abstention, not a guess."""
    async with session_scope() as session:
        result = await run_agent(
            query="What is the capital of France?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-abstain",
        )
    # Either the classifier routes it as unsupported, or evidence is insufficient;
    # either way the agent must abstain, never fabricate.
    assert result.failure in ("insufficient_evidence", None) or result.answer == ""
    assert "Paris" not in result.answer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_per_step_failure_does_not_abort_query(
    policy_doc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A step that raises at runtime is skipped; the rest of the plan still runs."""
    llm = ScriptedLLM(
        script={
            "planner": [
                {
                    "steps": [
                        {
                            "sub_question": "remote work policy",
                            "tool": "search_by_date",
                            "tool_args": {"date_from": "not-a-date"},  # raises inside tool
                        },
                        {
                            "sub_question": "remote work policy",
                            "tool": "search_documents",
                            "tool_args": {},
                        },
                    ],
                    "rationale": "first date-filtered, then broad",
                }
            ]
        }
    )
    monkeypatch.setattr("src.agents.orchestrator.get_llm_provider", lambda: llm)

    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-stepfail",
        )

    assert result.failure is None, f"one bad step must not kill the query: {result.failure}"
    assert "3 days" in result.answer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_steps_failing_yields_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = ScriptedLLM(
        script={
            "planner": [
                {
                    "steps": [
                        {
                            "sub_question": "anything",
                            "tool": "search_by_date",
                            "tool_args": {"date_from": "bad"},
                        },
                        {
                            "sub_question": "anything",
                            "tool": "search_by_date",
                            "tool_args": {"date_from": "bad"},
                        },
                    ],
                    "rationale": "all broken",
                }
            ]
        }
    )
    monkeypatch.setattr("src.agents.orchestrator.get_llm_provider", lambda: llm)

    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-allfail",
        )

    assert result.failure == "tool_failure"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_tool_steps_dropped_plan_still_valid(
    policy_doc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planner output referencing an unregistered tool is dropped, not executed."""
    llm = ScriptedLLM(
        script={
            "planner": [
                {
                    "steps": [
                        {"sub_question": "x", "tool": "web_search", "tool_args": {}},
                        {
                            "sub_question": "remote work policy",
                            "tool": "search_documents",
                            "tool_args": {},
                        },
                    ],
                    "rationale": "one bogus tool + one good",
                }
            ]
        }
    )
    monkeypatch.setattr("src.agents.orchestrator.get_llm_provider", lambda: llm)

    async with session_scope() as session:
        result = await run_agent(
            query="What is our remote work policy?",
            user=_employee(),
            session=session,
            conversation_id=None,
            retrieval_strategy="hybrid_reranked",
            top_k=10,
            trace_id="test-trace-unknowntool",
        )

    assert result.failure is None
    assert "3 days" in result.answer
