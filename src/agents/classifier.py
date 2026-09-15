"""Query classification — routes a query to the right strategy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from src.llm.provider import LLMProvider


class QueryClass(StrEnum):
    SIMPLE_FACTUAL = "simple_factual"
    COMPARATIVE = "comparative"
    TEMPORAL = "temporal"
    MULTI_HOP = "multi_hop"
    ANALYTICAL = "analytical"
    UNSUPPORTED = "unsupported"


@dataclass
class ClassificationResult:
    query_class: QueryClass
    confidence: float
    rationale: str


CLASSIFIER_PROMPT = """You are a query classifier. Given a user query, return one of these classes:
- simple_factual: direct factual lookup (e.g. "What is our remote work policy?")
- comparative: comparing two or more entities (e.g. "Compare Plan A and Plan B")
- temporal: asking about changes over time (e.g. "What changed in Q2?")
- multi_hop: requires multiple retrieval steps (e.g. "Summarize risks for project X in Q2")
- analytical: requires synthesis across multiple sources (e.g. "What are the trends?")
- unsupported: not answerable from organizational documents (e.g. "What's the weather?")

Return JSON: {{"class": "<one of above>", "confidence": <0..1>, "rationale": "<one sentence>"}}

Query: {query}
"""


async def classify_query(query: str, llm: LLMProvider) -> ClassificationResult:
    """Classify a user query."""
    prompt = CLASSIFIER_PROMPT.format(query=query)
    response = await llm.complete_json(prompt, temperature=0.0)
    try:
        cls = QueryClass(response["class"])
    except (KeyError, ValueError):
        cls = QueryClass.SIMPLE_FACTUAL
    return ClassificationResult(
        query_class=cls,
        confidence=float(response.get("confidence", 0.5)),
        rationale=response.get("rationale", ""),
    )
