"""Performance benchmark script — `python -m scripts.bench`."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main(
    output: str = typer.Option("docs/operations/performance.md", help="Output markdown file"),
    n: int = typer.Option(100, help="Number of iterations per benchmark"),
) -> None:
    """Run performance benchmarks."""
    asyncio.run(_bench(output=output, n=n))


async def _bench(*, output: str, n: int) -> None:
    results: dict[str, dict[str, float]] = {}

    # 1. Embedding throughput
    print(f"Benchmarking embeddings ({n} texts)...")
    # TODO: implement
    results["embedding"] = {"throughput_texts_per_s": 0.0, "p95_ms": 0.0}

    # 2. Retrieval latency
    print(f"Benchmarking retrieval ({n} queries)...")
    # TODO: implement
    results["retrieval"] = {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

    # 3. Reranker latency
    print(f"Benchmarking reranker ({n} candidate sets)...")
    # TODO: implement
    results["reranker"] = {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

    # 4. End-to-end query latency
    print(f"Benchmarking end-to-end ({n} queries)...")
    # TODO: implement
    results["e2e_query"] = {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

    # Write report
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Performance Benchmarks",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Iterations per benchmark: {n}",
        "",
        "## Results",
        "",
    ]
    for bench, metrics in results.items():
        lines.append(f"### {bench}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        for k, v in metrics.items():
            lines.append(f"| {k} | {v:.2f} |")
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- All benchmarks run on a single machine.",
            "- Replace the placeholder values above with real measurements from your environment.",
            "- **Do not fabricate numbers.** If a benchmark was not run, write `Not measured yet.`",
            "",
        ]
    )

    out_path.write_text("\n".join(lines))
    print(f"\nBenchmark report written to {out_path}")


if __name__ == "__main__":
    app()
