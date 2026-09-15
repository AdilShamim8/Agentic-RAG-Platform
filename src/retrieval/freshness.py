"""Document freshness — boost currently-effective chunks, penalize expired ones."""

from __future__ import annotations

from datetime import date

from src.retrieval.types import ScoredChunk


def apply_freshness_boost(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    """Apply freshness-aware score adjustments.

    - If effective_to < today: 0.5x penalty (expired)
    - If effective_from <= today AND effective_to is null or >= today: 1.1x boost (currently effective)
    - Otherwise: 1.0x (no change)
    """
    today = date.today()
    for c in chunks:
        if c.effective_to is not None and c.effective_to < today:
            c.score *= 0.5
        elif (
            c.effective_from is not None
            and c.effective_from <= today
            and (c.effective_to is None or c.effective_to >= today)
        ):
            c.score *= 1.1

    # Re-sort after score adjustment
    chunks.sort(key=lambda x: -x.score)
    return chunks
