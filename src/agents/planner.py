"""Planner — generates a list of sub-questions and tool assignments.

The prompt enumerates the registered tools WITH their allowed arguments so
the model does not hallucinate unsupported args (previously the planner
emitted e.g. {"query": ...} for search_documents, which the registry
rejected, and the whole query failed with tool_failure).

Parsed plans are sanitized before use:
- steps referencing unregistered tools are dropped
- steps whose args contain keys outside the tool schema are dropped
- the plan is capped at max_steps
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.agents.classifier import QueryClass
from src.agents.tools import list_tools
from src.llm.provider import LLMProvider


@dataclass
class PlanStep:
    sub_question: str
    tool: str  # search_documents | search_by_date | memory_search | get_document_versions
    tool_args: dict


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    rationale: str = ""
    dropped: list[PlanStep] = field(default_factory=list)  # invalid steps, kept for observability


DEFAULT_MAX_STEPS = 4


def _tool_catalog() -> str:
    lines = []
    for tool in list_tools():
        props = tool.schema.get("properties", {})
        required = tool.schema.get("required", [])
        args_json = json.dumps(
            {name: spec.get("type", "any") for name, spec in props.items()}, sort_keys=True
        )
        req_json = json.dumps(required, sort_keys=True)
        lines.append(f"- {tool.name}: {tool.description} args={args_json} required={req_json}")
    return "\n".join(lines)


def build_planner_prompt(query: str, query_class: str, feedback: str = "") -> str:
    feedback_block = ""
    if feedback:
        feedback_block = f"""
FEEDBACK from a previous attempt (the query was NOT answerable with what was
retrieved; change the sub-questions, tools, or filters - do not repeat the
same steps):
{feedback}
"""
    return f"""You are a planner. Given a user query and its classification, decompose it into retrieval steps.

Each step has:
- sub_question: a focused question for retrieval
- tool: exactly one of the registered tools listed below
- tool_args: a dict using ONLY the args declared for that tool (omit optional args you do not need)

Registered tools:
{_tool_catalog()}

Return JSON: {{"steps": [{{"sub_question": "...", "tool": "...", "tool_args": {{"...": "..."}}}}], "rationale": "..."}}

For simple_factual queries, return ONE step.
For multi_hop queries, return 2-4 steps in execution order.
For temporal queries, include a search_by_date step (args: date_from/date_to as ISO dates).
For comparative queries, return one step per entity.
For unsupported queries, return an empty steps list.

Classification: {query_class}
Query: {query}
{feedback_block}
"""


def sanitize_steps(steps: list[PlanStep], max_steps: int = DEFAULT_MAX_STEPS) -> list[PlanStep]:
    """Drop invalid steps (unknown tool / out-of-schema args) and cap the count."""
    from src.agents.tools import get_tool

    kept: list[PlanStep] = []
    for step in steps:
        tool = get_tool(step.tool)
        if tool is None:
            continue
        allowed_keys = set(tool.schema.get("properties", {}))
        if not set(step.tool_args or {}) <= allowed_keys:
            continue
        if not step.sub_question or not isinstance(step.sub_question, str):
            continue
        if len(kept) < max_steps:
            kept.append(step)
    return kept


async def plan(
    query: str,
    query_class: QueryClass,
    llm: LLMProvider,
    *,
    feedback: str = "",
    max_steps: int = DEFAULT_MAX_STEPS,
) -> Plan:
    """Generate an execution plan (sanitized against the live tool registry)."""
    if query_class.value == "unsupported":
        return Plan(steps=[], rationale="Query is unsupported; no plan needed.")
    prompt = build_planner_prompt(query, query_class.value, feedback=feedback)
    response = await llm.complete_json(prompt, temperature=0.0)
    raw_steps = [
        PlanStep(
            sub_question=s.get("sub_question", ""),
            tool=s.get("tool", ""),
            tool_args=s.get("tool_args", {}) or {},
        )
        for s in response.get("steps", [])
    ]
    kept = sanitize_steps(raw_steps, max_steps=max_steps)
    dropped = [s for s in raw_steps if s not in kept]
    return Plan(steps=kept, rationale=response.get("rationale", ""), dropped=dropped)
