"""Agent orchestrator — the main loop.

Run-loop:
  while not state.is_terminal():
      action = decide_next_action(state)
      result = execute(action, state)
      state.update(result)

This is a custom state machine, NOT LangGraph. The reasons are documented in
docs/decisions/ADR-004-agent-orchestration.md.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.deps.auth import AuthUser
from src.agents.citation_validator import validate_citations
from src.agents.classifier import QueryClass, classify_query
from src.agents.evidence_validator import check_evidence_sufficiency
from src.agents.generator import generate_answer
from src.agents.planner import Plan, plan
from src.agents.state import AgentState, AgentStateName
from src.agents.tools.registry import execute_tool
from src.core.failures import Failure
from src.llm.provider import get_llm_provider
from src.observability.tracing import traced_operation


async def run_agent(
    *,
    query: str,
    user: AuthUser,
    session: AsyncSession,
    conversation_id: str | None,
    retrieval_strategy: str,
    top_k: int | None,
    trace_id: str,
) -> Any:
    """Main entry point. Returns an object with .answer, .citations, .failure, .confidence, .cost_usd."""
    from apps.api.app.services.query_service import AgentResult

    llm = get_llm_provider()
    state = AgentState(
        query=query,
        user_id=user.id,
        user_role=user.role_slug,
        user_permissions=user.permissions,
        user_projects=user.projects,
        conversation_id=conversation_id or "",
        trace_id=trace_id,
    )

    try:
        async with asyncio.timeout(state.global_timeout_s):
            await _run_loop(state, llm, user, session, retrieval_strategy, top_k)
    except TimeoutError:
        state.force_terminal(reason="global_timeout", failure=Failure.LLM_TIMEOUT)

    return AgentResult(
        answer=state.answer or "I don't have enough evidence to answer this confidently.",
        citations=state.citations,
        failure=state.failure,
        confidence=_confidence(state),
        cost_usd=state.cost_usd,
        tool_call_count=state.tool_calls,
    )


async def _run_loop(
    state: AgentState,
    llm: Any,
    user: AuthUser,
    session: AsyncSession,
    retrieval_strategy: str,
    top_k: int | None,
) -> None:
    """The actual loop. Updates `state` in place."""

    # 1. Classify
    async with traced_operation("agent.classify", trace_id=state.trace_id):
        classification = await classify_query(state.query, llm)

    if classification.query_class == QueryClass.UNSUPPORTED:
        state.answer = "I don't have enough evidence to answer this confidently."
        state.failure = Failure.INSUFFICIENT_EVIDENCE
        state.current_state = AgentStateName.END
        return

    # 2. Plan
    async with traced_operation("agent.plan", trace_id=state.trace_id):
        plan_obj: Plan = await plan(state.query, classification.query_class, llm)

    if not plan_obj.steps:
        state.answer = "I don't have enough evidence to answer this confidently."
        state.failure = Failure.INSUFFICIENT_EVIDENCE
        state.current_state = AgentStateName.END
        return

    # 3. Execute each plan step (retrieve + rerank)
    for step in plan_obj.steps:
        if not state.can_continue():
            break
        if state.is_looping(step.tool, step.tool_args):
            state.failure = Failure.AGENT_LOOP
            state.current_state = AgentStateName.FAILED
            return

        state.steps += 1
        async with traced_operation("agent.tool", trace_id=state.trace_id, tool=step.tool):
            try:
                tool_result = await execute_tool(
                    tool_name=step.tool,
                    args=step.tool_args,
                    sub_question=step.sub_question,
                    user=user,
                    session=session,
                    retrieval_strategy=retrieval_strategy,
                    top_k=top_k,
                )
                state.record_tool_call(step.tool, step.tool_args)
                state.retrieved_chunks.extend(tool_result.chunks)
                state.cost_usd += tool_result.cost_usd
            except TimeoutError:
                state.failure = Failure.RETRIEVAL_TIMEOUT
                state.current_state = AgentStateName.FAILED
                return
            except Exception:
                state.failure = Failure.TOOL_FAILURE
                state.current_state = AgentStateName.FAILED
                return

    # 4. Evidence sufficiency
    async with traced_operation("agent.evidence_check", trace_id=state.trace_id):
        sufficient = await check_evidence_sufficiency(state.query, state.retrieved_chunks, llm)
    if not sufficient:
        state.answer = "I don't have enough evidence to answer this confidently."
        state.failure = Failure.INSUFFICIENT_EVIDENCE
        state.current_state = AgentStateName.END
        return

    # 5. Generate
    async with traced_operation("agent.generate", trace_id=state.trace_id):
        generation = await generate_answer(state.query, state.retrieved_chunks, llm)
    state.answer = generation.answer
    state.cost_usd += generation.cost_usd

    # 6. Validate citations
    async with traced_operation("agent.validate_citations", trace_id=state.trace_id):
        citations = await validate_citations(generation.answer, state.retrieved_chunks, llm)

    if not citations:
        state.answer = "I generated an answer I cannot verify. Withholding response."
        state.failure = Failure.HALLUCINATION_DETECTED
        state.current_state = AgentStateName.FAILED
        return

    state.citations = citations
    state.current_state = AgentStateName.END


def _confidence(state: AgentState) -> str:
    """Heuristic confidence: based on # citations + evidence sufficiency."""
    if state.failure is not None:
        return "low"
    if len(state.citations) >= 3:
        return "high"
    if len(state.citations) >= 1:
        return "medium"
    return "low"
