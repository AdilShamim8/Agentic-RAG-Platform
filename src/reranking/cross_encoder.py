"""Cross-encoder reranker using BGE-reranker-v2-m3."""

from __future__ import annotations

import asyncio
from typing import Any

from src.retrieval.types import ScoredChunk


class BGECrossEncoderReranker:
    """BGE-reranker-v2-m3 — multilingual cross-encoder."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        from FlagEmbedding import FlagLLMModel

        self._model = FlagLLMModel(model_name, use_fp16=True)

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int = 5
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        pairs = [(query, c.content) for c in candidates]
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(
            None,
            lambda: self._model.compute_score(pairs, normalize=True),
        )
        # Make sure scores is a list (single pair returns a float)
        if isinstance(scores, float):
            scores = [scores]
        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
        result = []
        for chunk, score in ranked[:top_k]:
            chunk.score = float(score)
            result.append(chunk)
        return result


async def rerank(
    reranker: Any, *, query: str, candidates: list[ScoredChunk], top_k: int
) -> list[ScoredChunk]:
    """Convenience function."""
    return await reranker.rerank(query, candidates, top_k)
