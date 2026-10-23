"""Compare evaluation reports and produce evals/reports/comparison.md.

Reads every *.json report in the reports directory and renders one row per
(baseline) from summary_by_baseline, plus honest notes about what was and
was NOT measured. Never fabricates a number: missing metrics render as
"Not measured."
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer()


def _fmt(value: object) -> str:
    if value is None:
        return "Not measured."
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


@app.command()
def main(reports_dir: str = typer.Option("evals/reports", help="Reports directory")) -> None:
    """Generate comparison.md from all *.json reports in reports_dir."""
    reports_path = Path(reports_dir)
    if not reports_path.exists():
        typer.echo(f"Reports directory does not exist: {reports_path}")
        raise typer.Exit(1)

    reports = []
    for f in sorted(reports_path.glob("*.json")):
        with open(f) as fh:
            reports.append(json.load(fh))

    if not reports:
        typer.echo("No reports found. Run `make eval` first.")
        raise typer.Exit(1)

    # Latest report wins per baseline (older reports are preserved on disk).
    per_baseline: dict[str, dict] = {}
    provider = reports[-1].get("provider", "?")
    corpus_sha = reports[-1].get("corpus_sha256", "?")
    for report in reports:
        for baseline, summary in (report.get("summary_by_baseline") or {}).items():
            per_baseline[baseline] = summary

    if not per_baseline:
        raise typer.Exit(
            "Reports contain no summary_by_baseline (legacy reports?). Re-run `make eval`."
        )

    lines = [
        "# Evaluation Comparison",
        "",
        f"Generated from {len(reports)} report(s) in `{reports_dir}/` "
        "(latest report per baseline wins).",
        "",
        f"- Provider mode: **{provider}**",
        f"- Fixture corpus: `evals/datasets/corpus_fixtures.jsonl` (sha256 {corpus_sha})",
        "- Deterministic metrics only; LLM-judge rubric scores require a real provider "
        "and are NOT included here (see docs/reviews/llm_judge_methodology.md).",
        "",
        "## Baseline summary",
        "",
        "| Baseline | Behavior compliance | Pattern faithfulness | Recall@k | MRR | "
        "Source hit rate | Verified citation rate | Unexpected failures | p95 latency (ms) |",
        "|----------|--------------------:|--------------------:|---------:|----:|"
        "---------------:|----------------------:|---------------------:|----------------:|",
    ]

    for baseline, s in per_baseline.items():
        lines.append(
            f"| {baseline} "
            f"| {_fmt(s.get('behavior_compliance'))} "
            f"| {_fmt(s.get('pattern_faithfulness'))} "
            f"| {_fmt(s.get('recall_at_k'))} "
            f"| {_fmt(s.get('mrr'))} "
            f"| {_fmt(s.get('expected_source_hit_rate'))} "
            f"| {_fmt(s.get('verified_citation_rate'))} "
            f"| {_fmt(s.get('unexpected_failure_rate'))} "
            f"| {_fmt(s.get('p95_latency_ms'))} |"
        )

    lines.extend(
        [
            "",
            "## Metric definitions",
            "",
            "- **Behavior compliance**: fraction of scored rows whose observed behavior "
            "matches the expected row behavior (answer/abstain/refuse/...).",
            "- **Pattern faithfulness**: fraction of answerable rows where every "
            "'+'-separated term of the expected answer pattern appears in the answer. "
            "A deterministic extractive-grounding proxy, NOT a judge score.",
            "- **Recall@k / MRR / source hit**: computed against the expected fixture "
            "chunk ids on rows that carry retrieval labels.",
            "- **Verified citation rate**: fraction of emitted citations that passed "
            "claim-level verification.",
            "- **Unexpected failures**: agent failures that violate the expected "
            "behavior (a safe refusal is NOT a failure).",
            "",
            "## Notes and limitations",
            "",
            "- All numbers are deterministic under the recorded provider mode; "
            "mock-mode answer quality reflects the deterministic extractive generator, "
            "not a production LLM.",
            "- **Do not fabricate numbers.** If a metric was not measured, the table "
            "says `Not measured.`",
            "- Fault-injection scenario rows (adversarial.jsonl) are covered by the "
            "deterministic test suite, not by these judge-free metrics; see "
            "docs/reviews/test_matrix.md.",
            "- A safe abstention/refusal on rows expecting content from unauthorized "
            "documents counts as compliant behavior, not as a retrieval miss.",
        ]
    )

    output_path = reports_path / "comparison.md"
    with open(output_path, "w") as fh:
        fh.write("\n".join(lines))
    typer.echo(f"Comparison written to {output_path}")


if __name__ == "__main__":
    app()
