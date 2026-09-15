"""Reranker base — provider abstraction."""

from __future__ import annotations

from typing import Protocol

from src.retrieval.types import ScoredChunk


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: list[ScoredChunk], top_k: int = 5
    ) -> list[ScoredChunk]: ...


_reranker: Reranker | None = None


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        from apps.api.app.core.config import settings
        from src.reranking.cross_encoder import BGECrossEncoderReranker

        _reranker = BGECrossEncoderReranker(model_name=settings.reranker_model)
    return _reranker
