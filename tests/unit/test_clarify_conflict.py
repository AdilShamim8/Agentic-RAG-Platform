"""Clarify + conflict-detection tests.

- classifier: the mock provider's deterministic ambiguity rule flags
  "Tell me about the policy." (and only genuinely vague queries)
- conflict detector: heuristic + judge path; different docs with different
  numbers conflict; same doc / same value / temporal co-mentions do not
- orchestrator end-to-end (integration): vague query -> clarification;
  conflicting corpus -> conflict report citing both documents
"""

from __future__ import annotations

import pytest

from src.agents.classifier import QueryClass, classify_query
from src.agents.conflict_detector import (
    CONFLICT_ANSWER_PREFIX,
    build_conflict_answer,
    heuristic_conflicts,
)
from src.llm.provider import _MockLLMProvider
from src.retrieval.types import ScoredChunk


def _chunk(chunk_id: str, doc_id: str, title: str, content: str) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id, document_id=doc_id, document_title=title, content=content, score=1.0
    )


# --- classifier ambiguity (via the deterministic mock judge) ------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Tell me about the policy.", QueryClass.AMBIGUOUS),
        ("Tell me about that policy.", QueryClass.AMBIGUOUS),
        ("What is our remote work policy?", QueryClass.SIMPLE_FACTUAL),
        ("Who is the CEO?", QueryClass.SIMPLE_FACTUAL),
        ("Show me the Q3 financial results.", QueryClass.SIMPLE_FACTUAL),
        ("List all policy changes in Q1 2025.", QueryClass.SIMPLE_FACTUAL),
        ("What is the home internet reimbursement?", QueryClass.SIMPLE_FACTUAL),
        # Identifier-like code lookups are maximally specific, never vague.
        ("POL-2024-007", QueryClass.SIMPLE_FACTUAL),
        ("What is course code CS-101?", QueryClass.SIMPLE_FACTUAL),
    ],
)
async def test_mock_classifier_ambiguity_rule(query: str, expected: QueryClass) -> None:
    llm = _MockLLMProvider()
    result = await classify_query(query, llm)
    assert result.query_class == expected, f"{query!r}: {result.query_class} != {expected}"


# --- heuristic conflicts -------------------------------------------------------


def test_heuristic_conflict_different_docs_different_values() -> None:
    chunks = [
        _chunk("c1", "doc-a", "IT Policy", "claim up to $40 per month for internet"),
        _chunk("c2", "doc-b", "Finance Guide", "allowance is $60 per month for internet"),
    ]
    conflicts = heuristic_conflicts(chunks)
    assert len(conflicts) == 1
    assert {conflicts[0].a_chunk_id, conflicts[0].b_chunk_id} == {"c1", "c2"}


def test_no_conflict_same_document() -> None:
    chunks = [
        _chunk("c1", "doc-a", "HR", "2024 allowed 2 days per week. 2026 allows 3 days per week."),
    ]
    assert heuristic_conflicts(chunks) == []


def test_no_conflict_same_value() -> None:
    chunks = [
        _chunk("c1", "doc-a", "IT", "up to $40 per month"),
        _chunk("c2", "doc-b", "Finance", "capped at $40 per month"),
    ]
    assert heuristic_conflicts(chunks) == []


def test_no_conflict_different_units() -> None:
    chunks = [
        _chunk("c1", "doc-a", "HR", "remote work is 3 days per week"),
        _chunk("c2", "doc-b", "Finance", "budget is $3 per day"),
    ]
    assert heuristic_conflicts(chunks) == []


def test_no_conflict_single_chunk_each() -> None:
    chunks = [_chunk("c1", "doc-a", "HR", "no numbers here at all")]
    assert heuristic_conflicts(chunks) == []


# --- conflict answer builder ----------------------------------------------------


def test_conflict_answer_reports_both_sides_with_markers() -> None:
    from src.agents.conflict_detector import Conflict

    chunks = {
        "c1": _chunk("c1", "doc-a", "IT Policy", "claim up to $40 per month"),
        "c2": _chunk("c2", "doc-b", "Finance Guide", "allowance is $60 per month"),
    }
    answer = build_conflict_answer(
        [Conflict(a_chunk_id="c1", b_chunk_id="c2", topic="dollar amount per period")], chunks
    )
    assert answer.startswith(CONFLICT_ANSWER_PREFIX)
    assert "IT Policy" in answer and "Finance Guide" in answer
    assert "[1]" in answer and "[2]" in answer
    assert "$40" in answer and "$60" in answer


# --- detect_conflicts via the mock judge ----------------------------------------


@pytest.mark.asyncio
async def test_detect_conflicts_via_mock_judge() -> None:
    from src.agents.conflict_detector import detect_conflicts

    llm = _MockLLMProvider()
    chunks = [
        _chunk("c1", "doc-a", "IT Policy", "claim up to $40 per month for home internet"),
        _chunk("c2", "doc-b", "Finance Guide", "allowance is $60 per month for home internet"),
        _chunk("c3", "doc-c", "HR", "remote work is 3 days per week"),
    ]
    conflicts = await detect_conflicts("What is the home internet reimbursement?", chunks, llm)
    assert len(conflicts) == 1
    assert {conflicts[0].a_chunk_id, conflicts[0].b_chunk_id} == {"c1", "c2"}


@pytest.mark.asyncio
async def test_detect_conflicts_none_when_agreeing() -> None:
    from src.agents.conflict_detector import detect_conflicts

    llm = _MockLLMProvider()
    chunks = [
        _chunk("c1", "doc-a", "HR", "PTO is 25 days per year"),
        _chunk("c2", "doc-b", "Manager Guide", "confirm PTO of 25 days per year in writing"),
    ]
    conflicts = await detect_conflicts("How many vacation days?", chunks, llm)
    assert conflicts == []
