"""Unit tests for RRF (Reciprocal Rank Fusion)."""

from __future__ import annotations

import pytest

from src.retrieval.hybrid import rrf_fuse
from src.retrieval.types import ScoredChunk


def _make(chunk_id: str, score: float) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=chunk_id,
        document_id="doc",
        document_title="t",
        content="c",
        score=score,
    )


def test_rrf_fuse_basic():
    dense = [_make("a", 0.9), _make("b", 0.8), _make("c", 0.7)]
    lexical = [_make("b", 5.0), _make("d", 4.0), _make("a", 3.0)]

    fused = rrf_fuse(dense, lexical, top_n=10, k=60)

    # Both lists contain "a" and "b" — they should be top-ranked
    assert fused[0].chunk_id in {"a", "b"}
    assert fused[1].chunk_id in {"a", "b"}


def test_rrf_fuse_ranks_are_one_based():
    """Top of a single list contributes 1/(k+1), per the RRF paper (1-based ranks)."""
    dense = [_make("a", 0.9), _make("b", 0.8)]
    fused = rrf_fuse(dense, [], top_n=10, k=60)
    assert fused[0].chunk_id == "a"
    assert fused[0].score == pytest.approx(1.0 / 61.0)
    assert fused[1].score == pytest.approx(1.0 / 62.0)


def test_rrf_fuse_chunk_appearing_in_both_lists():
    """A chunk ranked 1st in both lists scores 2 * 1/(k+1)."""
    dense = [_make("a", 0.9)]
    lexical = [_make("a", 5.0), _make("b", 4.0)]
    fused = rrf_fuse(dense, lexical, top_n=10, k=60)
    assert fused[0].chunk_id == "a"
    assert fused[0].score == pytest.approx(2.0 / 61.0)


def test_rrf_fuse_does_not_mutate_inputs():
    dense = [_make("a", 0.9), _make("b", 0.8)]
    lexical = [_make("b", 5.0), _make("a", 3.0)]
    fused = rrf_fuse(dense, lexical, top_n=10)
    # Original score fields untouched; fused objects are new instances
    assert dense[0].score == 0.9 and dense[1].score == 0.8
    assert lexical[0].score == 5.0 and lexical[1].score == 3.0
    assert all(f is not dense[0] for f in fused)
    assert fused[0].score not in {0.9, 0.8, 5.0, 3.0}  # fused score, not an input score


def test_rrf_fuse_top_n():
    dense = [_make(f"d{i}", 0.9 - i * 0.1) for i in range(10)]
    lexical = [_make(f"l{i}", 10 - i) for i in range(10)]
    fused = rrf_fuse(dense, lexical, top_n=5)
    assert len(fused) == 5


def test_rrf_fuse_empty():
    assert rrf_fuse([], [], top_n=5) == []


def test_rrf_fuse_unique_to_one_list():
    dense = [_make("only_dense", 0.9)]
    lexical = [_make("only_lexical", 5.0)]
    fused = rrf_fuse(dense, lexical, top_n=10)
    chunk_ids = {c.chunk_id for c in fused}
    assert chunk_ids == {"only_dense", "only_lexical"}
