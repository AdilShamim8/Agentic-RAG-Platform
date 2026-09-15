"""Planner — generates a list of sub-questions and tool assignments."""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.classifier import QueryClass
from src.llm.provider import LLMProvider


@dataclass
class PlanStep:
    sub_question: str
    tool: str  # search_documents | search_by_date | memory_search | ...
    tool_args: dict


@dataclass
class Plan:
    steps: list[PlanStep]
    rationale: str


PLANNER_PROMPT = """You are a planner. Given a user query and its classification, decompose it into retrieval steps.

Each step has:
- sub_question: a focused question for retrieval
- tool: one of "search_documents", "search_by_date", "memory_search", "get_document_versions"
- tool_args: a dict of arguments for the tool

Return JSON: {{"steps": [{{"sub_question": "...", "tool": "...", "tool_args": {{...}}}}], "rationale": "..."}}

For simple_factual queries, return ONE step.
For multi_hop queries, return 2-4 steps in execution order.
For temporal queries, include a search_by_date step.
For comparative queries, return one step per entity.
For unsupported queries, return an empty steps list.

Classification: {query_class}
Query: {query}
"""


async def plan(query: str, query_class: QueryClass, llm: LLMProvider) -> Plan:
    """Generate an execution plan."""
    if query_class.value == "unsupported":
        return Plan(steps=[], rationale="Query is unsupported; no plan needed.")
    prompt = PLANNER_PROMPT.format(query_class=query_class.value, query=query)
    response = await llm.complete_json(prompt, temperature=0.0)
    steps = [
        PlanStep(
            sub_question=s["sub_question"],
            tool=s["tool"],
            tool_args=s.get("tool_args", {}),
        )
        for s in response.get("steps", [])
    ]
    return Plan(steps=steps, rationale=response.get("rationale", ""))
