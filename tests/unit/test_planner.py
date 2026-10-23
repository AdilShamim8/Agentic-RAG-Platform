"""Planner unit tests: prompt construction, plan sanitization, caps."""

from __future__ import annotations

from src.agents.planner import (
    DEFAULT_MAX_STEPS,
    PlanStep,
    build_planner_prompt,
    sanitize_steps,
)
from src.agents.tools import list_tools


def test_planner_prompt_lists_registered_tools_and_args() -> None:
    prompt = build_planner_prompt("What is our remote work policy?", "simple_factual")
    tool_names = {t.name for t in list_tools()}
    assert tool_names, "no tools registered - package import broken"
    for name in tool_names:
        assert name in prompt, f"tool {name} missing from planner prompt"
    # search_documents args must be documented (schema key is document_type)
    assert "department" in prompt and "document_type" in prompt
    assert "search_by_date" in prompt and "date_from" in prompt


def test_planner_prompt_includes_feedback_block() -> None:
    prompt = build_planner_prompt(
        "q", "simple_factual", feedback="Previous attempt found nothing relevant."
    )
    assert "FEEDBACK" in prompt
    assert "Previous attempt found nothing relevant." in prompt
    assert "do not repeat" in prompt


def test_sanitize_drops_unknown_tools() -> None:
    steps = [
        PlanStep(sub_question="q1", tool="search_documents", tool_args={}),
        PlanStep(sub_question="q2", tool="not_a_real_tool", tool_args={}),
    ]
    kept = sanitize_steps(steps)
    assert [s.tool for s in kept] == ["search_documents"]


def test_sanitize_drops_out_of_schema_args() -> None:
    """The old failure mode: planner invents 'query' for search_documents."""
    steps = [
        PlanStep(sub_question="q", tool="search_documents", tool_args={"query": "x"}),
        PlanStep(sub_question="q2", tool="search_documents", tool_args={"department": "hr"}),
    ]
    kept = sanitize_steps(steps)
    assert [s.tool_args for s in kept] == [{"department": "hr"}]


def test_sanitize_drops_empty_sub_question() -> None:
    steps = [PlanStep(sub_question="", tool="search_documents", tool_args={})]
    assert sanitize_steps(steps) == []


def test_sanitize_caps_step_count() -> None:
    steps = [
        PlanStep(sub_question=f"q{i}", tool="search_documents", tool_args={}) for i in range(10)
    ]
    kept = sanitize_steps(steps, max_steps=DEFAULT_MAX_STEPS)
    assert len(kept) == DEFAULT_MAX_STEPS
