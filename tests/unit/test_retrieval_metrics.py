"""Unit tests for retrieval metrics (Recall@K, Precision@K, MRR, nDCG)."""

from __future__ import annotations

from src.evaluation.retrieval_metrics import (
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_recall_at_k():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"b", "d", "z"}
    assert recall_at_k(retrieved, relevant, k=5) == 2 / 3
    assert recall_at_k(retrieved, relevant, k=2) == 1 / 3
    assert recall_at_k(retrieved, relevant, k=1) == 0.0


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["a", "b"], set(), k=2) == 0.0


def test_precision_at_k():
    retrieved = ["a", "b", "c", "d", "e"]
    relevant = {"b", "d"}
    assert precision_at_k(retrieved, relevant, k=5) == 2 / 5
    assert precision_at_k(retrieved, relevant, k=2) == 1 / 2


def test_mrr():
    retrieved = ["a", "b", "c"]
    relevant = {"c"}
    assert mrr(retrieved, relevant) == 1 / 3

    retrieved = ["a", "b", "c"]
    relevant = {"a"}
    assert mrr(retrieved, relevant) == 1.0

    retrieved = ["a", "b", "c"]
    relevant = {"z"}
    assert mrr(retrieved, relevant) == 0.0


def test_ndcg_at_k():
    retrieved = ["a", "b", "c"]
    relevant = {"a", "b"}
    # DCG = 1/log2(2) + 1/log2(3) = 1 + 0.6309 = 1.6309
    # IDCG = 1/log2(2) + 1/log2(3) = 1.6309
    expected = 1.0
    assert abs(ndcg_at_k(retrieved, relevant, k=3) - expected) < 1e-6

    retrieved = ["c", "a", "b"]
    relevant = {"a", "b"}
    # DCG = 0 + 1/log2(3) + 1/log2(4) = 0.6309 + 0.5 = 1.1309
    # IDCG = 1.6309
    expected = 1.1309 / 1.6309
    assert abs(ndcg_at_k(retrieved, relevant, k=3) - expected) < 1e-3
