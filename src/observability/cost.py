"""Cost tracking — computes and records per-request cost."""

from __future__ import annotations

from src.llm.provider import compute_cost


def compute_request_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    return compute_cost(model, tokens_in, tokens_out)
