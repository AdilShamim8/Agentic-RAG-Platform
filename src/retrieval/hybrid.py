"""Hybrid retrieval — Reciprocal Rank Fusion of dense + lexical results.

RRF is preferred over score-based fusion because dense cosine scores and lexical
BM25/TS scores are on incomparable scales. RRF only uses ranks, not scores.
"""

from __future__ import annotations

from src.retrieval.types import ScoredChunk


def rrf_fuse(
    dense_results: list[ScoredChunk],
    lexical_results: list[ScoredChunk],
    top_n: int = 50,
    k: int = 60,
) -> list[ScoredChunk]:
    """Reciprocal Rank Fusion.

    score(chunk) = sum over both lists of 1 / (k + rank_in_list)

    Args:
        dense_results: ranked dense results
        lexical_results: ranked lexical results
        top_n: how many fused results to return
        k: RRF constant (60 is the standard value from the original paper)
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, ScoredChunk] = {}

    for rank, r in enumerate(dense_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        chunk_map[r.chunk_id] = r

    for rank, r in enumerate(lexical_results):
        scores[r.chunk_id] = scores.get(r.chunk_id, 0.0) + 1.0 / (k + rank)
        if r.chunk_id not in chunk_map:
            chunk_map[r.chunk_id] = r

    # Sort by fused score, return top_n
    sorted_ids = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
    result = []
    for chunk_id, score in sorted_ids:
        chunk = chunk_map[chunk_id]
        # Replace the original score with the fused score
        chunk.score = score
        result.append(chunk)
    return result
