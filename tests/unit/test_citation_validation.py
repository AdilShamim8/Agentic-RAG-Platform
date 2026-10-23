"""Citation validation unit tests.

Contract: claims come from the ANSWER (not from the evidence), markers are
bounds-checked, the judge is schema-validated, and every judge problem fails
closed (unsupported).
"""

from __future__ import annotations

import pytest

from src.agents.citation_validator import (
    parse_markers,
    sentence_span,
    validate_citations,
)
from src.llm.provider import _MockLLMProvider
from src.retrieval.types import ScoredChunk


def _chunk(i: int, content: str) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=f"chunk-{i}",
        document_id=f"doc-{i}",
        document_title=f"Doc {i}",
        content=content,
        score=0.9,
        page=1,
        section="1",
    )


class JudgeLLM(_MockLLMProvider):
    """Mock whose citation-verifier verdicts are scripted per (claim_index, chunk_id).

    `verdicts` sets supported true/false; `omit` removes the row entirely so the
    validator exercises the omitted-pair (fail-closed) path.
    """

    def __init__(
        self,
        verdicts: dict[tuple[int, str], bool] | None = None,
        raise_on_verify: bool = False,
        respond_malformed: bool = False,
        omit: set[tuple[int, str]] | None = None,
    ) -> None:
        super().__init__()
        self.verdicts = verdicts or {}
        self.raise_on_verify = raise_on_verify
        self.respond_malformed = respond_malformed
        self.omit = omit or set()

    async def complete_json(self, prompt: str, *, temperature: float = 0.0) -> dict:
        if "citation verifier" in prompt.lower():
            if self.raise_on_verify:
                raise RuntimeError("judge unavailable")
            if self.respond_malformed:
                return {"results": "not-a-list"}
            import re

            chunk_ids = re.findall(r"\[chunk_id=([^\]]+)\]", prompt)
            results = [
                {
                    "claim_index": i,
                    "chunk_id": cid,
                    "supported": self.verdicts.get((i, cid), False),
                }
                for i in range(8)
                for cid in chunk_ids
                if (i, cid) not in self.omit
            ]
            return {"results": results}
        return await super().complete_json(prompt, temperature=temperature)


def test_parse_markers_positions() -> None:
    answer = "Alpha [1]. Beta [2] and again [2]. Gamma [3]."
    markers = parse_markers(answer)
    assert [m[0] for m in markers] == [1, 2, 2, 3]
    # positions point at the actual marker text
    for num, start, end in markers:
        assert answer[start:end] == f"[{num}]"


def test_sentence_span_finds_containing_sentence() -> None:
    answer = "First claim here [1]. Second claim there [2]. Tail."
    assert "[1]" in sentence_span(answer, answer.index("[1]"))
    assert sentence_span(answer, answer.index("[1]")).startswith("First claim")
    assert sentence_span(answer, answer.index("[2]")).startswith("Second claim")


@pytest.mark.asyncio
async def test_valid_citation_verified_against_answer_claim() -> None:
    chunks = [_chunk(1, "Employees may work remotely up to 3 days per week.")]
    answer = "Employees can work remotely up to 3 days per week [1]."
    outcome = await validate_citations(answer, chunks, _MockLLMProvider())
    assert outcome.invalid_markers == []
    assert len(outcome.citations) == 1
    assert outcome.citations[0].chunk_id == "chunk-1"
    assert outcome.citations[0].verified is True
    assert outcome.judge_error is False


@pytest.mark.asyncio
async def test_out_of_range_marker_fails_whole_answer() -> None:
    """A fabricated [5] with 1 chunk means the answer cannot be trusted."""
    chunks = [_chunk(1, "Some evidence.")]
    answer = "Claim one [1]. Claim two [5]."
    outcome = await validate_citations(answer, chunks, _MockLLMProvider())
    assert outcome.invalid_markers == [5]
    assert outcome.citations == []


@pytest.mark.asyncio
async def test_real_chunk_but_claim_not_supported_is_dropped() -> None:
    """The citation is real but does not support the claim -> dropped."""
    chunks = [_chunk(1, "The kitchen serves lunch at noon.")]
    answer = "Employees may work remotely up to 3 days per week [1]."
    llm = JudgeLLM(verdicts={(0, "chunk-1"): False})
    outcome = await validate_citations(answer, chunks, llm)
    assert outcome.citations == []
    assert outcome.judge_error is False


@pytest.mark.asyncio
async def test_multi_claim_partial_grounding_withholds_chunk() -> None:
    """Two claims cite the same chunk; one is unsupported -> chunk unverified."""
    chunks = [_chunk(1, "Remote work allowed 3 days. Also the office opens at 9am.")]
    answer = (
        "Employees may work remotely up to 3 days per week [1]. "
        "The stock price will double next year [1]."
    )
    llm = JudgeLLM(verdicts={(0, "chunk-1"): True, (1, "chunk-1"): False})
    outcome = await validate_citations(answer, chunks, llm)
    assert outcome.citations == []


@pytest.mark.asyncio
async def test_judge_error_fails_closed() -> None:
    chunks = [_chunk(1, "Evidence text.")]
    answer = "Something supported [1]."
    outcome = await validate_citations(answer, chunks, JudgeLLM(raise_on_verify=True))
    assert outcome.judge_error is True
    assert outcome.citations == []


@pytest.mark.asyncio
async def test_malformed_judge_output_fails_closed() -> None:
    chunks = [_chunk(1, "Evidence text.")]
    answer = "Something supported [1]."
    outcome = await validate_citations(answer, chunks, JudgeLLM(respond_malformed=True))
    assert outcome.judge_error is True
    assert outcome.citations == []


@pytest.mark.asyncio
async def test_omitted_pair_fails_closed() -> None:
    """Judge response missing a (claim, chunk) pair -> that pair is unsupported."""
    chunks = [_chunk(1, "Evidence."), _chunk(2, "More evidence.")]
    answer = "First fact [1]. Second fact [2]."
    # Verdicts provided only for chunk-1; chunk-2 row omitted entirely
    llm = JudgeLLM(verdicts={(0, "chunk-1"): True}, omit={(1, "chunk-2")})
    outcome = await validate_citations(answer, chunks, llm)
    assert outcome.judge_error is True  # the omitted pair was noticed
    # chunk-1 verified, chunk-2 fail-closed to unverified
    assert [c.chunk_id for c in outcome.citations] == ["chunk-1"]


@pytest.mark.asyncio
async def test_duplicate_marker_dedupe() -> None:
    chunks = [_chunk(1, "Evidence.")]
    answer = "Claim A [1]. Claim B [1]."
    llm = JudgeLLM(verdicts={(0, "chunk-1"): True, (1, "chunk-1"): True})
    outcome = await validate_citations(answer, chunks, llm)
    assert outcome.duplicate_markers == [1]
    assert len(outcome.citations) == 1  # deduped by chunk_id
    assert outcome.citations[0].verified is True


@pytest.mark.asyncio
async def test_no_markers_returns_empty_without_judging() -> None:
    chunks = [_chunk(1, "Evidence.")]
    answer = "I don't have enough evidence to answer this confidently."
    llm = _MockLLMProvider()
    outcome = await validate_citations(answer, chunks, llm)
    assert outcome.citations == []
    assert outcome.invalid_markers == []
    assert outcome.uncited_sentences != []


@pytest.mark.asyncio
async def test_uncited_sentences_reported() -> None:
    chunks = [_chunk(1, "Evidence.")]
    answer = "Cited fact [1]. This trailing sentence has no marker."
    outcome = await validate_citations(answer, chunks, _MockLLMProvider())
    assert outcome.uncited_sentences == ["This trailing sentence has no marker."]
    assert len(outcome.citations) == 1  # the cited part still verifies
