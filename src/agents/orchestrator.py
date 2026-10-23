"""Agent orchestrator — the main loop.

Run-loop (custom state machine, NOT LangGraph; see
docs/decisions/ADR-004-agent-orchestration.md):

    classify
    loop (bounded by state.max_replans):
        plan (with feedback from previous attempt)
        execute steps (per-step failures tolerated; a plan only fails hard
                       if every step failed and nothing was retrieved)
        evidence sufficiency check
        sufficient  -> break to generation
        insufficient -> replan (if budget remains) else abstain
    generate answer
    validate citations

Budgets: state.max_steps, state.max_tool_calls, state.max_replans, and a
global asyncio timeout wrap the whole run.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.deps.auth import AuthUser
from src.agents.citation_validator import validate_citations
from src.agents.classifier import QueryClass, classify_query
from src.agents.evidence_validator import check_evidence_sufficiency
from src.agents.generator import ABSTENTION_ANSWER, generate_answer
from src.agents.planner import plan
from src.agents.state import AgentState, AgentStateName
from src.agents.tools import execute_tool
from src.core.failures import Failure, user_message
from src.llm.provider import get_llm_provider
from src.observability.tracing import traced_operation
from src.security.prompt_injection import classify_input


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
        replans=state.replans,
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

    # 1b. Prompt-injection screen (Layer 1 of the documented defense).
    #     The regex runs first (no LLM call); the LLM judge is only consulted
    #     when the regex finds nothing. A judge failure is conservative-allow
    #     (documented in prompt_injection.py) - output side is still sanitized.
    async with traced_operation("agent.injection_check", trace_id=state.trace_id):
        injection = await classify_input(state.query, llm)
    if injection.is_injection:
        state.answer = user_message(Failure.UNSAFE_CONTENT)
        state.failure = Failure.UNSAFE_CONTENT
        state.current_state = AgentStateName.FAILED
        return

    feedback = ""
    while True:
        # 2. Plan (sanitized against the live tool registry; includes feedback on replans)
        async with traced_operation("agent.plan", trace_id=state.trace_id, replan=state.replans):
            plan_obj = await plan(state.query, classification.query_class, llm, feedback=feedback)

        if not plan_obj.steps:
            state.answer = "I don't have enough evidence to answer this confidently."
            state.failure = Failure.INSUFFICIENT_EVIDENCE
            state.current_state = AgentStateName.END
            return

        # 3. Execute plan steps. Per-step failures are tolerated; a step that
        #    raises does not abort the query.
        executed = 0
        failed = 0
        for step in plan_obj.steps:
            if not state.can_continue():
                break
            if state.is_looping(step.tool, step.tool_args):
                state.failure = Failure.AGENT_LOOP
                state.current_state = AgentStateName.FAILED
                return

            state.steps += 1
            executed += 1
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
                except Exception:
                    failed += 1
                    continue

        # Every step failed and nothing was retrieved -> hard tool failure.
        if executed > 0 and failed == executed and not state.retrieved_chunks:
            state.failure = Failure.TOOL_FAILURE
            state.current_state = AgentStateName.FAILED
            return

        # 4. Evidence sufficiency
        async with traced_operation("agent.evidence_check", trace_id=state.trace_id):
            sufficient = await check_evidence_sufficiency(state.query, state.retrieved_chunks, llm)

        if sufficient:
            break

        # 5. Insufficient evidence: bounded replan with feedback
        if state.replans < state.max_replans and state.can_continue():
            state.replans += 1
            feedback = (
                "A previous retrieval attempt did not find sufficient evidence. "
                "Produce different sub-questions; consider different tools or broader filters. "
                "Do not repeat the same steps."
            )
            continue

        state.answer = "I don't have enough evidence to answer this confidently."
        state.failure = Failure.INSUFFICIENT_EVIDENCE
        state.current_state = AgentStateName.END
        return

    # 6. Generate
    async with traced_operation("agent.generate", trace_id=state.trace_id):
        generation = await generate_answer(state.query, state.retrieved_chunks, llm)
    state.answer = generation.answer
    state.cost_usd += generation.cost_usd

    # 6b. Output safety: block known injection patterns leaked into the answer
    from src.security.prompt_injection import sanitize_output

    sanitized, blocked = sanitize_output(generation.answer)
    if blocked:
        state.answer = user_message(Failure.UNSAFE_CONTENT)
        state.failure = Failure.UNSAFE_CONTENT
        state.current_state = AgentStateName.FAILED
        return
    state.answer = sanitized

    # 7. Validate citations against the answer's own claims
    async with traced_operation("agent.validate_citations", trace_id=state.trace_id):
        validation = await validate_citations(generation.answer, state.retrieved_chunks, llm)

    from src.agents.citation_validator import parse_markers

    has_markers = bool(parse_markers(generation.answer))

    if validation.invalid_markers:
        # Fabricated / out-of-range markers: the answer is not trustworthy.
        state.answer = user_message(Failure.CITATION_MISMATCH)
        state.failure = Failure.CITATION_MISMATCH
        state.current_state = AgentStateName.FAILED
        return

    if not has_markers:
        if generation.answer.strip() == ABSTENTION_ANSWER:
            # Well-defined abstention path: no citations required.
            state.answer = generation.answer
            state.failure = Failure.INSUFFICIENT_EVIDENCE
            state.current_state = AgentStateName.END
            return
        # Factual-looking answer with no citation markers at all.
        state.answer = user_message(Failure.CITATION_MISMATCH)
        state.failure = Failure.CITATION_MISMATCH
        state.current_state = AgentStateName.FAILED
        return

    if not validation.citations:
        # Markers exist but no claim survived verification.
        state.answer = user_message(Failure.HALLUCINATION_DETECTED)
        state.failure = Failure.HALLUCINATION_DETECTED
        state.current_state = AgentStateName.FAILED
        return

    state.citations = validation.citations
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
