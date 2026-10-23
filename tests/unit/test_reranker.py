"""Reranker contract tests.

FlagEmbedding is not installed in CI/test environments; these tests inject a
fake `FlagEmbedding` module exposing exactly the documented public API
(`FlagReranker`). If src code imports any other symbol (e.g. the
non-existent FlagLLMModel), construction raises ImportError and the tests
fail - that is the regression guard.
"""

from __future__ import annotations

import sys
import types
from typing import ClassVar

import pytest

from src.reranking.cross_encoder import BGECrossEncoderReranker, rerank
from src.retrieval.types import ScoredChunk


class _FakeFlagReranker:
    """Deterministic stand-in: score = fraction of query words found in content."""

    instances: ClassVar[list[_FakeFlagReranker]] = []

    def __init__(self, model_name: str, use_fp16: bool = False) -> None:
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.calls: list[tuple[list[tuple[str, str]], bool]] = []
        _FakeFlagReranker.instances.append(self)

    def compute_score(self, pairs: list[tuple[str, str]], normalize: bool = False):
        assert normalize is True, "reranker must request normalized scores"
        scores = []
        for query, content in pairs:
            words = set(query.lower().split())
            hits = sum(1 for w in words if w in content.lower())
            scores.append(hits / len(words) if words else 0.0)
        return scores if len(pairs) > 1 else scores[0]


@pytest.fixture(autouse=True)
def fake_flagembedding(monkeypatch: pytest.MonkeyPatch):
    module = types.SimpleNamespace(FlagReranker=_FakeFlagReranker)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    _FakeFlagReranker.instances.clear()
    yield
    _FakeFlagReranker.instances.clear()


def _chunk(i: int, content: str, score: float = 0.5) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=f"chunk-{i}",
        document_id=f"doc-{i}",
        document_title=f"Doc {i}",
        content=content,
        score=score,
    )


@pytest.mark.asyncio
async def test_reranker_uses_flagreranker_symbol() -> None:
    """Construction must go through FlagEmbedding.FlagReranker (public API)."""
    BGECrossEncoderReranker(model_name="BAAI/bge-reranker-v2-m3")
    assert _FakeFlagReranker.instances, "FlagReranker was never constructed"
    assert _FakeFlagReranker.instances[0].model_name == "BAAI/bge-reranker-v2-m3"


@pytest.mark.asyncio
async def test_rerank_orders_by_relevance_and_caps_top_k() -> None:
    reranker = BGECrossEncoderReranker()
    candidates = [
        _chunk(1, "unrelated filler text"),
        _chunk(2, "the remote work policy allows 3 days"),
        _chunk(3, "remote work policy details here"),
        _chunk(4, "also unrelated"),
    ]
    result = await reranker.rerank("remote work policy", candidates, top_k=2)
    assert [c.chunk_id for c in result] == ["chunk-2", "chunk-3"]
    assert all(c.score > 0 for c in result)
    # original candidates were not mutated in place
    assert candidates[1].score == 0.5 and candidates[1].chunk_id == "chunk-2"


@pytest.mark.asyncio
async def test_rerank_single_candidate_scalar_score() -> None:
    """compute_score returns a scalar for one pair - code must handle it."""
    reranker = BGECrossEncoderReranker()
    result = await reranker.rerank("alpha beta", [_chunk(9, "alpha text")], top_k=1)
    assert len(result) == 1
    assert result[0].score == 0.5  # 1 of 2 query words present


@pytest.mark.asyncio
async def test_rerank_empty_candidates() -> None:
    reranker = BGECrossEncoderReranker()
    assert await reranker.rerank("anything", [], top_k=5) == []


@pytest.mark.asyncio
async def test_rerank_mismatched_scores_raises() -> None:
    reranker = BGECrossEncoderReranker()

    class _Broken(_FakeFlagReranker):  # type: ignore[name-has-no-annot]
        def compute_score(self, pairs, normalize=False):
            return [0.1]  # wrong length on purpose

    reranker._model = _Broken("x")
    with pytest.raises(RuntimeError, match="scores"):
        await reranker.rerank("q", [_chunk(1, "a"), _chunk(2, "b")], top_k=2)


@pytest.mark.asyncio
async def test_rerank_convenience_function() -> None:
    reranker = BGECrossEncoderReranker()
    out = await rerank(reranker, query="policy", candidates=[_chunk(1, "policy text")], top_k=1)
    assert out[0].chunk_id == "chunk-1"
