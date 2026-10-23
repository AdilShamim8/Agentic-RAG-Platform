"""Cross-encoder reranker using BGE-reranker-v2-m3.

Uses FlagEmbedding.FlagReranker - the actual public API for
bge-reranker-v2-m3. (The previous implementation imported
`FlagLLMModel`, which does not exist in FlagEmbedding, so
`get_reranker()` raised ImportError at first use and every
`hybrid_reranked` retrieval failed.)
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from src.retrieval.types import ScoredChunk


class BGECrossEncoderReranker:
    """BGE-reranker-v2-m3 — multilingual cross-encoder."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        from FlagEmbedding import FlagReranker

        self._model = FlagReranker(model_name, use_fp16=True)

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int = 5
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        pairs = [(query, c.content) for c in candidates]
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            None,
            lambda: self._model.compute_score(pairs, normalize=True),
        )
        # compute_score returns a scalar for a single pair and a sequence
        # (list or ndarray) otherwise.
        scores = [scores] if isinstance(scores, (int, float)) else list(scores)
        if len(scores) != len(candidates):
            raise RuntimeError(
                f"Reranker returned {len(scores)} scores for {len(candidates)} candidates"
            )
        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
        # Return new chunk objects: never mutate shared candidates in place.
        return [replace(chunk, score=float(score)) for chunk, score in ranked[:top_k]]


async def rerank(
    reranker: Any, *, query: str, candidates: list[ScoredChunk], top_k: int
) -> list[ScoredChunk]:
    """Convenience function."""
    return await reranker.rerank(query, candidates, top_k)
