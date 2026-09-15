"""Citation builder — parses [N] markers from generated answers."""

from __future__ import annotations

import re

from src.citations.types import CitationResult
from src.retrieval.types import ScoredChunk


def parse_markers(answer: str) -> list[int]:
    """Return all unique [N] markers in order of appearance."""
    return [int(m) for m in re.findall(r"\[(\d+)\]", answer)]


def build_citations(answer: str, chunks: list[ScoredChunk]) -> list[CitationResult]:
    """Map [N] markers in the answer to chunks. Returns CitationResult list."""
    citations: list[CitationResult] = []
    for n in parse_markers(answer):
        idx = n - 1
        if 0 <= idx < len(chunks):
            c = chunks[idx]
            citations.append(
                CitationResult(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    document_title=c.document_title,
                    page=c.page,
                    section=c.section,
                    url=c.url,
                    snippet=c.content[:300],
                    verified=False,  # validation happens in citation_validator
                )
            )
    return citations
