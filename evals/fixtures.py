"""Fixture corpus support for the evaluation harness.

The fixture corpus (evals/datasets/corpus_fixtures.jsonl) is a SYNTHETIC
corpus with stable document UUIDs and deterministic chunk UUIDs
(uuid5 of "agentic-rag-fixture:{doc_id}:{chunk_index}"), so:

- golden dataset rows can reference REAL, reproducible chunk/document ids
  (no placeholders), and
- seeding is idempotent across runs and environments.

The corpus is explicitly labeled synthetic: ground-truth labels describe
this fixture corpus, never real user data.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

FIXTURES_PATH = Path(__file__).parent / "datasets" / "corpus_fixtures.jsonl"
FIXTURE_NS_PREFIX = "agentic-rag-fixture:"


def fixture_chunk_id(doc_id: str, chunk_index: int) -> str:
    """Deterministic chunk UUID for a fixture document chunk."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{FIXTURE_NS_PREFIX}{doc_id}:{chunk_index}"))


def load_fixture_spec(path: Path | None = None) -> list[dict]:
    """Load and structurally validate the fixture corpus spec."""
    target = path or FIXTURES_PATH
    if not target.exists():
        raise FileNotFoundError(f"Fixture corpus not found: {target}")
    docs: list[dict] = []
    seen_ids: set[str] = set()
    with open(target) as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{target}:{line_no}: invalid JSON ({exc})") from exc
            for field in (
                "doc_id",
                "title",
                "doc_type",
                "department",
                "access_policy",
                "effective_from",
                "effective_to",
                "chunks",
            ):
                if field not in doc:
                    raise ValueError(f"{target}:{line_no}: missing field {field!r}")
            try:
                uuid.UUID(doc["doc_id"])
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{target}:{line_no}: doc_id is not a UUID") from exc
            if doc["doc_id"] in seen_ids:
                raise ValueError(f"{target}:{line_no}: duplicate doc_id {doc['doc_id']}")
            seen_ids.add(doc["doc_id"])
            if not isinstance(doc["chunks"], list) or not doc["chunks"]:
                raise ValueError(f"{target}:{line_no}: chunks must be a non-empty list")
            if not all(isinstance(c, str) and c.strip() for c in doc["chunks"]):
                raise ValueError(f"{target}:{line_no}: chunk contents must be non-empty strings")
            docs.append(doc)
    if not docs:
        raise ValueError(f"{target}: fixture corpus is empty")
    return docs


def fixture_index() -> dict[str, dict]:
    """doc_id -> spec, plus computed chunk ids per doc."""
    return {doc["doc_id"]: doc for doc in load_fixture_spec()}


def all_fixture_chunk_ids() -> dict[str, list[str]]:
    """doc_id -> [chunk uuids] (deterministic)."""
    out: dict[str, list[str]] = {}
    for doc in load_fixture_spec():
        out[doc["doc_id"]] = [fixture_chunk_id(doc["doc_id"], i) for i in range(len(doc["chunks"]))]
    return out


def corpus_hash() -> str:
    """Stable content hash of the fixture spec (for report reproducibility)."""
    import hashlib

    blob = FIXTURES_PATH.read_bytes() if FIXTURES_PATH.exists() else b""
    return hashlib.sha256(blob).hexdigest()[:16]
