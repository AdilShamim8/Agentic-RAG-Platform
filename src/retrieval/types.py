"""Retrieval types — shared dataclasses for retrieval results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class ScoredChunk:
    """A retrieved chunk with a relevance score and full metadata."""

    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    page: int | None = None
    section: str | None = None
    url: str | None = None
    version: int = 1
    effective_from: date | None = None
    effective_to: date | None = None
    access_policy: dict | None = None


@dataclass(slots=True)
class RetrievalConfig:
    strategy: str = "hybrid_reranked"  # dense | lexical | hybrid | hybrid_reranked
    top_k: int = 10
    candidate_count: int = 50
    similarity_threshold: float = 0.2
    reranker_top_k: int = 5
    filters: dict | None = None
