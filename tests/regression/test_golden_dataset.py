"""Regression tests — golden dataset quality gate."""

from __future__ import annotations

import pytest


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_faithfulness_above_threshold():
    """Faithfulness across the golden dataset must be >= 0.85."""
    # TODO: load golden, run all queries, compute faithfulness, assert >= threshold
    # For now: skip until the eval pipeline is wired up
    pytest.skip("Golden dataset eval not yet wired")


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_hallucination_below_threshold():
    """Hallucination rate across the golden dataset must be <= 0.10."""
    pytest.skip("Golden dataset eval not yet wired")


@pytest.mark.regression
@pytest.mark.asyncio
async def test_agent_termination_under_30s():
    """All golden queries must terminate within 30 seconds."""
    pytest.skip("Golden dataset eval not yet wired")
