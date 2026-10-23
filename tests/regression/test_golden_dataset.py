"""Regression tests — golden dataset quality gate (real, no longer skipped).

Runs the smoke evaluation against the seeded fixture corpus with the
deterministic mock provider and asserts the agreed gates. Thresholds are
tied to the measured fixed baseline (baseline_6_agentic measured
behavior=0.959, pattern=0.686, recall=0.857, unexpected_fail=0.041 on the
full golden set) with a safety margin; they are floors, not targets.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _run_eval(dataset: str, baselines: str) -> dict:
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reports"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.run",
                "--dataset",
                dataset,
                "--baselines",
                baselines,
                "--output-dir",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        reports = sorted(out.glob("*.json"))
        assert reports, proc.stdout + proc.stderr
        return json.loads(reports[-1].read_text())


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_behavior_compliance_above_threshold() -> None:
    report = _run_eval("evals/datasets/golden_smoke.jsonl", "baseline_6_agentic")
    summary = report["summary_by_baseline"]["baseline_6_agentic"]
    assert summary["behavior_compliance"] is not None, "behavior must be measured"
    assert summary["behavior_compliance"] >= 0.9, summary


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_pattern_faithfulness_above_threshold() -> None:
    report = _run_eval("evals/datasets/golden_smoke.jsonl", "baseline_6_agentic")
    summary = report["summary_by_baseline"]["baseline_6_agentic"]
    assert summary["pattern_faithfulness"] is not None, "pattern metric must be measured"
    assert summary["pattern_faithfulness"] >= 0.6, summary


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_unexpected_failure_below_threshold() -> None:
    report = _run_eval("evals/datasets/golden_smoke.jsonl", "baseline_6_agentic")
    summary = report["summary_by_baseline"]["baseline_6_agentic"]
    assert summary["unexpected_failure_rate"] <= 0.05, summary


@pytest.mark.regression
@pytest.mark.asyncio
async def test_golden_dataset_zero_unauthorized_citations() -> None:
    report = _run_eval("evals/datasets/golden_smoke.jsonl", "baseline_6_agentic")
    summary = report["summary_by_baseline"]["baseline_6_agentic"]
    assert summary["unauthorized_citations"] == 0, summary


@pytest.mark.regression
@pytest.mark.asyncio
async def test_agent_termination_under_30s() -> None:
    """All smoke queries must terminate within the 30s global budget."""
    report = _run_eval("evals/datasets/golden_smoke.jsonl", "baseline_6_agentic")
    slow = [r for r in report["results"] if r["latency_ms"] > 30_000]
    assert (
        not slow
    ), f"queries exceeded the global timeout: {[(r['query_id'], r['latency_ms']) for r in slow]}"


@pytest.mark.regression
@pytest.mark.asyncio
async def test_full_golden_no_placeholder_labels() -> None:
    """The committed datasets must not contain placeholder ground truth."""
    from evals.fixtures import all_fixture_chunk_ids
    from evals.run import load_dataset

    rows = load_dataset("evals/datasets/golden.jsonl", all_fixture_chunk_ids())
    labeled = [r for r in rows if r.get("expected_chunks")]
    assert len(labeled) >= 25, "most answerable rows must carry real chunk labels"
