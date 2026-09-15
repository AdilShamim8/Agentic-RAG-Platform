"""Evidence sufficiency checker."""

from __future__ import annotations

from src.llm.provider import LLMProvider
from src.retrieval.types import ScoredChunk

SUFFICIENCY_PROMPT = """You are an evidence sufficiency judge.

Given a question and a list of evidence chunks, decide whether the evidence is sufficient to answer the question.

Return JSON: {{"sufficient": true|false, "reason": "..."}}

A question is answerable if the evidence contains explicit, relevant information that directly addresses the question.
Insufficient means: the evidence is empty, irrelevant, or only tangentially related.

QUESTION:
{question}

EVIDENCE:
{evidence}

JUDGE:
"""


async def check_evidence_sufficiency(
    query: str, chunks: list[ScoredChunk], llm: LLMProvider
) -> bool:
    """Return True if the evidence is sufficient to answer the query."""
    if not chunks:
        return False
    evidence = "\n\n".join(f"- {c.content[:500]}" for c in chunks[:5])
    prompt = SUFFICIENCY_PROMPT.format(question=query, evidence=evidence)
    response = await llm.complete_json(prompt, temperature=0.0)
    return bool(response.get("sufficient", False))
