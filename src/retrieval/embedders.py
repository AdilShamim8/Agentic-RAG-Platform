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


class _HashedBagEmbedder:
    """Deterministic hashed bag-of-words embedder for tests and offline evals.

    Selected by EMBEDDING_MODEL names starting with "test-" (e.g.
    "test-hashed-bag"), mirroring the sk-test mock LLM. It maps each
    alphanumeric token to a stable dimension (sha1 of the token mod dim)
    and produces L2-normalized count vectors, so cosine similarity
    approximates vocabulary overlap. This lets the whole retrieval stack
    (dense, hybrid, rerankers, evaluations) run with no network access,
    no model downloads, and fully reproducible results.

    NOT a semantic embedder - never use for production. Outputs are
    documented as approximate in evaluation reports.
    """

    def __init__(self, model_name: str = "test-hashed-bag") -> None:
        import hashlib
        import re

        self._model_name = model_name
        self.dim = 1024
        self._token_re = re.compile(r"[a-z0-9]+")
        self._hashlib = hashlib

    def _vector(self, text: str) -> list[float]:
        import math

        vec = [0.0] * self.dim
        tokens = self._token_re.findall(text.lower())
        for token in tokens:
            digest = self._hashlib.sha1(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


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
    """Singleton accessor. Picks the embedder based on settings.

    EMBEDDING_MODEL starting with "test-" selects the deterministic hashed
    bag-of-words embedder (offline tests/evals, see _HashedBagEmbedder).
    """
    global _embedder
    if _embedder is None:
        if settings.embedding_model.startswith("test-"):
            _embedder = _HashedBagEmbedder(model_name=settings.embedding_model)
        elif settings.embedding_model.startswith("text-embedding"):
            _embedder = _OpenAIEmbedder(model_name=settings.embedding_model)
        else:
            _embedder = _LocalBGEEmbedder(model_name=settings.embedding_model)
    return _embedder
