"""Embedder providers — local BGE-m3 or OpenAI text-embedding-3-large.

Use a provider abstraction so the rest of the code is vendor-agnostic.
"""

from __future__ import annotations

from typing import Protocol

from apps.api.app.core.config import settings


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class _LocalBGEEmbedder:
    """Local BGE-m3 embedder (sentence-transformers)."""

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(model_name, use_fp16=True)
        self.dim = 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # BGE-m3 is sync; run in threadpool
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, batch_size=32, max_length=8192)["dense_vecs"],
        )
        return result.tolist()


class _OpenAIEmbedder:
    """OpenAI text-embedding-3-large embedder."""

    def __init__(self, model_name: str = "text-embedding-3-large") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model_name
        self.dim = 3072

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await self._client.embeddings.create(model=self._model, input=texts)
        return [d.embedding for d in result.data]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Singleton accessor. Picks the embedder based on settings."""
    global _embedder
    if _embedder is None:
        if settings.embedding_model.startswith("text-embedding"):
            _embedder = _OpenAIEmbedder(model_name=settings.embedding_model)
        else:
            _embedder = _LocalBGEEmbedder(model_name=settings.embedding_model)
    return _embedder
