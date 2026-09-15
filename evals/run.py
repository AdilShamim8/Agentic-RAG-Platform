"""Evaluation runner — `python -m evals.run`.

Loads a golden dataset, runs each query through the configured baseline,
collects metrics, and writes a report.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer

app = typer.Typer()


@dataclass
class ExperimentConfig:
    name: str
    dataset: str
    baselines: list[str]
    output_dir: str = "evals/reports"


@dataclass
class QueryResult:
    query_id: str
    query: str
    category: str
    answer: str
    citations: list[dict]
    retrieved_chunk_ids: list[str]
    latency_ms: int
    cost_usd: float
    failure: str | None
    expected_chunks: list[str]
    expected_behavior: str
    metrics: dict


def load_golden(path: str) -> list[dict]:
    """Load golden.jsonl."""
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


async def run_one(item: dict, baseline: str) -> QueryResult:
    """Run a single query through the system using the given baseline config."""
    # TODO: implement — call the API or service layer
    return QueryResult(
        query_id=item["id"],
        query=item["query"],
        category=item["category"],
        answer="[not implemented]",
        citations=[],
        retrieved_chunk_ids=[],
        latency_ms=0,
        cost_usd=0.0,
        failure=None,
        expected_chunks=item.get("expected_chunks", []),
        expected_behavior=item.get("expected_behavior", "answer"),
        metrics={},
    )


async def run_experiment(config: ExperimentConfig) -> dict:
    """Run a full experiment: load dataset, run each query, aggregate metrics."""
    dataset = load_golden(config.dataset)
    all_results: list[QueryResult] = []

    for baseline in config.baselines:
        print(f"Running baseline: {baseline}")
        for item in dataset:
            result = await run_one(item, baseline)
            all_results.append(result)

    # Aggregate metrics
    # TODO: compute retrieval metrics, generation metrics, system metrics

    report = {
        "experiment": config.name,
        "dataset": config.dataset,
        "timestamp": datetime.now(UTC).isoformat(),
        "total_queries": len(all_results),
        "baselines": config.baselines,
        "results": [asdict(r) for r in all_results],
        "summary": {
            # TODO: fill in
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "avg_cost_usd": 0,
            "failure_rate": 0,
        },
    }
    return report


@app.command()
def main(
    dataset: str = typer.Option("evals/datasets/golden.jsonl", help="Path to golden dataset"),
    baselines: str = typer.Option("all", help="Comma-separated baseline names or 'all'"),
    output_dir: str = typer.Option("evals/reports", help="Output directory"),
) -> None:
    """Run evaluation."""
    if baselines == "all":
        baseline_list = [
            "baseline_1_naive",
            "baseline_2_dense",
            "baseline_3_lexical",
            "baseline_4_hybrid",
            "baseline_5_hybrid_reranked",
            "baseline_6_agentic",
        ]
    else:
        baseline_list = [b.strip() for b in baselines.split(",")]

    config = ExperimentConfig(
        name=f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        dataset=dataset,
        baselines=baseline_list,
        output_dir=output_dir,
    )

    report = asyncio.run(run_experiment(config))

    output_path = Path(output_dir) / f"{config.name}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    app()
