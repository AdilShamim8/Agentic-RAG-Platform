"""Generator — produces a grounded answer with inline citation markers."""

from __future__ import annotations

from dataclasses import dataclass

from src.llm.provider import LLMProvider
from src.retrieval.types import ScoredChunk


@dataclass
class GenerationResult:
    answer: str
    cost_usd: float


GENERATOR_PROMPT = """You are a grounded Q&A assistant. Rules:
1. Only use the provided evidence. Do not use outside knowledge.
2. Cite every factual claim with [N] markers matching the evidence index below.
3. If the evidence does not answer the question, say: "I don't have enough evidence to answer this confidently."
4. Do not speculate. Do not paraphrase evidence into stronger claims.
5. Be concise — at most 3 sentences unless the question explicitly asks for detail.

EVIDENCE:
{evidence}

QUESTION:
{question}

ANSWER:
"""


async def generate_answer(
    query: str, chunks: list[ScoredChunk], llm: LLMProvider
) -> GenerationResult:
    """Generate an answer with [N] citation markers."""
    if not chunks:
        return GenerationResult(
            answer="I don't have enough evidence to answer this confidently.",
            cost_usd=0.0,
        )

    evidence = "\n\n".join(
        f"[{i+1}] (chunk_id={c.chunk_id}, page={c.page}, section={c.section})\n{c.content}"
        for i, c in enumerate(chunks)
    )
    prompt = GENERATOR_PROMPT.format(evidence=evidence, question=query)
    response = await llm.complete(prompt, temperature=0.1, max_tokens=500)
    return GenerationResult(answer=response.text, cost_usd=response.cost_usd)
