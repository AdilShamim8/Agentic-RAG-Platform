"""Query service — orchestrates a single agentic RAG query.

This is the heart of the system. It wires together:
- agent orchestrator (planner, classifier, loop)
- retrieval engine (dense / lexical / hybrid / reranked)
- memory (short-term + long-term)
- citation builder + validator
- failure handler
- observability (tracing, metrics, cost)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.deps.auth import AuthUser
from apps.api.app.routers.query import Citation, QueryResponse
from src.agents.orchestrator import run_agent
from src.citations.types import CitationResult
from src.core.failures import Failure
from src.observability.metrics import record_cost, record_query
from src.observability.tracing import traced_operation


async def run_agentic_query(
    *,
    query: str,
    user: AuthUser,
    session: AsyncSession,
    conversation_id: str | None,
    retrieval_strategy: str,
    top_k: int | None,
    trace_id: str,
) -> QueryResponse:
    """Run a single agentic RAG query end-to-end.

    Returns a QueryResponse with answer, citations, trace_id, confidence,
    and an optional failure field if the agent could not produce a grounded answer.
    """
    start = time.perf_counter()

    async with traced_operation(
        "rag.query",
        trace_id=trace_id,
        user_id=user.id,
        query_hash=hash(query),  # do NOT log raw query (PII)
        retrieval_strategy=retrieval_strategy,
    ) as span:
        # 1. Run the agent
        try:
            agent_result = await run_agent(
                query=query,
                user=user,
                session=session,
                conversation_id=conversation_id,
                retrieval_strategy=retrieval_strategy,
                top_k=top_k,
                trace_id=trace_id,
            )
        except TimeoutError:
            agent_result = AgentResult(
                answer="The model is taking too long. Please try again.",
                citations=[],
                failure=Failure.LLM_TIMEOUT,
                confidence="low",
                cost_usd=0.0,
            )

        # 2. Build citations
        citations = [
            Citation(
                chunk_id=str(c.chunk_id),
                document_id=str(c.document_id),
                document_title=c.document_title,
                page=c.page,
                section=c.section,
                url=c.url,
                snippet=c.snippet,
                verified=c.verified,
            )
            for c in agent_result.citations
        ]

        # 3. Persist message
        # TODO: persist to `messages` table with trace_id

        # 4. Record metrics
        latency_ms = int((time.perf_counter() - start) * 1000)
        record_query(
            status="ok" if agent_result.failure is None else "failure", latency_ms=latency_ms
        )
        record_cost(agent_result.cost_usd)

        # 5. Span attributes
        span.set_attributes(
            {
                "rag.latency_ms": latency_ms,
                "rag.citations.count": len(citations),
                "rag.failure": agent_result.failure.value if agent_result.failure else "",
                "rag.confidence": agent_result.confidence,
                "rag.cost_usd": agent_result.cost_usd,
            }
        )

        return QueryResponse(
            answer=agent_result.answer,
            citations=citations,
            trace_id=trace_id,
            conversation_id=conversation_id or str(uuid.uuid4()),
            confidence=agent_result.confidence,
            failure=agent_result.failure.value if agent_result.failure else None,
            metadata={
                "latency_ms": latency_ms,
                "cost_usd": agent_result.cost_usd,
                "tool_calls": agent_result.tool_call_count,
            },
        )


@dataclass(slots=True)
class AgentResult:
    answer: str
    citations: list[CitationResult]
    failure: Failure | None
    confidence: str  # low | medium | high
    cost_usd: float = 0.0
    tool_call_count: int = 0
