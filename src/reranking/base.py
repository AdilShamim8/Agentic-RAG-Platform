"""Reranker base — provider abstraction.

Selection (mirrors the sk-test mock LLM / test- embedders):
- RERANKER_MODEL starting with "test-" -> deterministic passthrough reranker
  (keeps candidates ordered by their existing score; no model download).
- otherwise -> BGECrossEncoderReranker (FlagEmbedding, real model).
"""

from __future__ import annotations

from typing import Protocol

from src.retrieval.types import ScoredChunk


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int = 5
    ) -> list[ScoredChunk]: ...


class _PassthroughReranker:
    """Deterministic no-op reranker for tests/offline evals.

    Sorts by the incoming score and returns the top_k unchanged. This is NOT
    a relevance model - it exists so hybrid_reranked can run end-to-end
    deterministically without downloading FlagEmbedding models.
    """

    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int = 5
    ) -> list[ScoredChunk]:
        ordered = sorted(candidates, key=lambda c: -c.score)
        return ordered[:top_k]


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        from apps.api.app.core.config import settings

        if settings.reranker_model.startswith("test-"):
            _reranker = _PassthroughReranker()
        else:
            from src.reranking.cross_encoder import BGECrossEncoderReranker

            _reranker = BGECrossEncoderReranker(model_name=settings.reranker_model)
    return _reranker
