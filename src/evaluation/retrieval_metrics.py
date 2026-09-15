"""Retrieval metrics — Recall@K, Precision@K, MRR, nDCG."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def recall_at_k(retrieved_ids: list[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of relevant items in the top K retrieved."""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top_k = retrieved_ids[:k]
    return len(set(top_k) & relevant) / len(relevant)


def precision_at_k(retrieved_ids: list[str], relevant_ids: Iterable[str], k: int) -> float:
    """Fraction of top-K retrieved that are relevant."""
    relevant = set(relevant_ids)
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    return len(set(top_k) & relevant) / k


def mrr(retrieved_ids: list[str], relevant_ids: Iterable[str]) -> float:
    """Mean Reciprocal Rank — 1/rank of first relevant item."""
    relevant = set(relevant_ids)
    for i, rid in enumerate(retrieved_ids, 1):
        if rid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: Iterable[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K."""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0

    dcg = 0.0
    for i, rid in enumerate(retrieved_ids[:k], 1):
        if rid in relevant:
            dcg += 1.0 / np.log2(i + 1)

    # Ideal DCG = sum of 1/log2(i+1) for i=1..min(k, len(relevant))
    ideal_n = min(k, len(relevant))
    idcg = sum(1.0 / np.log2(i + 1) for i in range(1, ideal_n + 1))

    return dcg / idcg if idcg > 0 else 0.0
