"""Compare baseline reports and produce evals/reports/comparison.md."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main(reports_dir: str = typer.Option("evals/reports", help="Reports directory")) -> None:
    """Generate comparison.md from all *.json reports in reports_dir."""
    reports_path = Path(reports_dir)
    if not reports_path.exists():
        print(f"Reports directory does not exist: {reports_path}")
        raise typer.Exit(1)

    reports = []
    for f in reports_path.glob("*.json"):
        with open(f) as fh:
            reports.append(json.load(fh))

    if not reports:
        print("No reports found. Run `make eval` first.")
        raise typer.Exit(1)

    lines = [
        "# Evaluation Comparison",
        "",
        f"Generated from {len(reports)} report(s) in `{reports_dir}/`.",
        "",
        "## Baseline summary",
        "",
        "| Baseline | Retrieval | Reranker | Faithfulness | Citation correctness | Hallucination rate | p95 latency (ms) | Cost / request (USD) |",
        "|----------|-----------|----------|-------------:|---------------------:|-------------------:|-----------------:|---------------------:|",
    ]

    for r in reports:
        # TODO: extract real metrics from the report
        lines.append(f"| {r.get('experiment', '?')} | ? | ? | ? | ? | ? | ? | ? |")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- All metrics are computed against the golden dataset (`evals/datasets/golden.jsonl`).",
            "- Faithfulness and hallucination rate use an LLM-judge calibrated on 20 hand-labeled items.",
            "- Latency is measured on a 4-core / 16 GB RAM machine with the reranker running on CPU.",
            "- If a cell is empty, the metric was not measured for that baseline.",
            "- **Do not fabricate numbers.** If you did not run the experiment, write `Not measured yet.`",
            "",
        ]
    )

    output_path = reports_path / "comparison.md"
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Comparison written to {output_path}")


if __name__ == "__main__":
    app()
