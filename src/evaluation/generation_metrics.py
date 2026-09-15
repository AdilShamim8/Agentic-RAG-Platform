"""Generation metrics — faithfulness, citation correctness, hallucination rate.

Uses Ragas for faithfulness + custom LLM-judge metrics for citation correctness.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.llm.provider import LLMProvider


@dataclass
class GenerationMetrics:
    faithfulness: float  # all claims supported by evidence (0..1)
    answer_correctness: float  # answer matches expected (0..1)
    context_relevance: float  # retrieved context is relevant (0..1)
    citation_correctness: float  # every [N] marker maps to a supporting chunk (0..1)
    citation_completeness: float  # every supported claim has a citation (0..1)
    hallucination_rate: float  # fraction of unsupported claims (0..1)
    abstention_correctness: float | None = None  # for negative queries


async def faithfulness_via_ragas(answer: str, evidence: list[str]) -> float:
    """Use Ragas faithfulness metric."""
    # TODO: implement with ragas
    return 0.0


CITATION_CORRECTNESS_PROMPT = """You are a citation correctness judge.

For each citation marker [N] in the answer, decide whether the cited evidence actually supports the claim.

Return JSON: {{"correctness": 0.0..1.0, "issues": ["..."]}}

ANSWER:
{answer}

EVIDENCE:
{evidence}
"""


async def citation_correctness(
    answer: str, evidence: list[str], llm: LLMProvider
) -> tuple[float, list[str]]:
    """LLM-judge: are all [N] markers supported by their cited chunk?"""
    prompt = CITATION_CORRECTNESS_PROMPT.format(
        answer=answer,
        evidence="\n\n".join(f"[{i+1}] {e}" for i, e in enumerate(evidence)),
    )
    response = await llm.complete_json(prompt, temperature=0.0)
    return float(response.get("correctness", 0.0)), response.get("issues", [])


HALLUCINATION_PROMPT = """You are a hallucination detector. Given an answer and the supporting evidence,
list every claim in the answer that is NOT supported by the evidence.

Return JSON: {{"unsupported_claims": ["...", "..."], "rate": 0.0..1.0}}
Where rate = len(unsupported_claims) / total_claims.

ANSWER:
{answer}

EVIDENCE:
{evidence}
"""


async def hallucination_rate(
    answer: str, evidence: list[str], llm: LLMProvider
) -> tuple[float, list[str]]:
    """Returns (rate, unsupported_claims)."""
    prompt = HALLUCINATION_PROMPT.format(
        answer=answer,
        evidence="\n\n".join(f"[{i+1}] {e}" for i, e in enumerate(evidence)),
    )
    response = await llm.complete_json(prompt, temperature=0.0)
    return float(response.get("rate", 0.0)), response.get("unsupported_claims", [])
