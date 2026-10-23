"""Dataset validation contract tests (no DB needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.fixtures import all_fixture_chunk_ids, fixture_chunk_id, load_fixture_spec
from evals.run import BASELINE_NAMES, load_dataset

FIX = all_fixture_chunk_ids()


def _write(tmp_path: Path, rows: list[dict]) -> str:
    target = tmp_path / "ds.jsonl"
    with open(target, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return str(target)


def _valid_row(rid: str = "t-001") -> dict:
    doc_id = next(iter(FIX))
    return {
        "id": rid,
        "category": "simple_factual",
        "query": "What is our remote work policy?",
        "expected_answer_pattern": "employees may work remotely",
        "expected_chunks": [FIX[doc_id][0]],
        "expected_documents": [doc_id],
        "expected_behavior": "answer",
        "access_role": "employee",
    }


def test_fixture_corpus_loads_and_is_deterministic() -> None:
    specs = load_fixture_spec()
    assert len(specs) >= 15
    # Deterministic chunk ids
    doc_id = specs[0]["doc_id"]
    assert fixture_chunk_id(doc_id, 0) == fixture_chunk_id(doc_id, 0)


def test_dataset_accepts_valid_rows(tmp_path: Path) -> None:
    rows = [_valid_row(), _valid_row("t-002")]
    rows[1]["expected_behavior"] = "abstain"
    rows[1]["expected_chunks"] = []
    rows[1]["expected_answer_pattern"] = ""
    loaded = load_dataset(_write(tmp_path, rows), FIX)
    assert len(loaded) == 2


def test_dataset_rejects_placeholder_chunk_ids(tmp_path: Path) -> None:
    row = _valid_row()
    row["expected_chunks"] = ["chunk-uuid-placeholder-1"]
    with pytest.raises(ValueError, match="placeholder chunk id"):
        load_dataset(_write(tmp_path, [row]), FIX)


def test_dataset_rejects_placeholder_doc_ids(tmp_path: Path) -> None:
    row = _valid_row()
    row["expected_documents"] = ["doc-uuid-placeholder-1"]
    with pytest.raises(ValueError, match="placeholder doc id"):
        load_dataset(_write(tmp_path, [row]), FIX)


def test_dataset_rejects_unknown_chunk_ids(tmp_path: Path) -> None:
    row = _valid_row()
    row["expected_chunks"] = ["b47229fb-bc46-5f0e-bfdc-69297ccdc18d-deadbeef"]
    with pytest.raises(ValueError, match="not in the fixture corpus"):
        load_dataset(_write(tmp_path, [row]), FIX)


def test_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(_write(tmp_path, [_valid_row(), _valid_row()]), FIX)


def test_dataset_rejects_unknown_behavior_and_role(tmp_path: Path) -> None:
    row = _valid_row()
    row["expected_behavior"] = "explode"
    with pytest.raises(ValueError, match="unknown expected_behavior"):
        load_dataset(_write(tmp_path, [row]), FIX)
    row2 = _valid_row("t-009")
    row2["access_role"] = "intern"
    with pytest.raises(ValueError, match="unknown access_role"):
        load_dataset(_write(tmp_path, [row2]), FIX)


def test_dataset_rejects_missing_fields(tmp_path: Path) -> None:
    row = _valid_row()
    del row["query"]
    with pytest.raises(ValueError, match="missing field 'query'"):
        load_dataset(_write(tmp_path, [row]), FIX)


def test_real_datasets_validate() -> None:
    """The committed golden/adversarial datasets must pass validation."""
    for name in ("golden.jsonl", "golden_smoke.jsonl", "adversarial.jsonl"):
        path = f"evals/datasets/{name}"
        rows = load_dataset(path, FIX)
        assert rows, f"{name} is empty"


def test_baseline_configs_exist() -> None:
    for baseline in BASELINE_NAMES:
        cfg = Path(f"evals/baselines/{baseline}.json")
        assert cfg.exists(), f"missing config {cfg}"
