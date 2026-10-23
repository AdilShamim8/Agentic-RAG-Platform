"""Cross-source conflict detection.

When the top-ranked evidence for a query contains materially different
answers to the SAME question (e.g. two current documents stating different
reimbursement rates), silently picking one source would fabricate
certainty. The agent instead reports the conflict and cites both sides.

Rules (mirrored by the deterministic mock judge in tests/CI):
- Only chunks from DIFFERENT documents can conflict; two passages inside
  one document are the document's own problem, not a source conflict.
- Temporal versions of a policy (a superseded document vs. its current
  replacement) are NOT conflicts - the question "what changed" is
  legitimate. Default retrieval only returns currently-effective
  documents anyway (see src/retrieval/freshness.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.llm.provider import LLMProvider
from src.retrieval.types import ScoredChunk

# Prefix of the conflict-report answer; the eval harness and tests key on it.
CONFLICT_ANSWER_PREFIX = "The retrieved sources conflict"

MAX_PASSAGES = 5

CONFLICT_DETECTOR_PROMPT = """You are a source conflict detector.

Given a question and evidence passages, decide whether two passages from DIFFERENT documents give materially different answers to the question (different numbers, dates, or decisions for the same fact).

Rules:
- Only passages from different documents can conflict.
- A superseded/temporal version of a policy next to its current version is NOT a conflict - it answers "what changed over time".
- Minor wording differences are NOT conflicts.

Return JSON: {{"conflicts": [{{"a": "<chunk_id>", "b": "<chunk_id>", "topic": "<the disputed fact in a few words>"}}]}}
Return an empty list when there is no conflict.

QUESTION:
{question}

EVIDENCE:
{evidence}

JUDGE:
"""


@dataclass(slots=True)
class Conflict:
    """A detected disagreement between two chunks from different documents."""

    a_chunk_id: str
    b_chunk_id: str
    topic: str


async def detect_conflicts(
    query: str, chunks: list[ScoredChunk], llm: LLMProvider
) -> list[Conflict]:
    """Return the conflicts among the top evidence chunks (may be empty)."""
    if len(chunks) < 2:
        return []

    # One passage per document, capped: conflicts are about the top evidence.
    by_doc: dict[str, ScoredChunk] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, chunk)
    passages = list(by_doc.values())[:MAX_PASSAGES]
    if len(passages) < 2:
        return []

    evidence = "\n\n".join(
        f"- [chunk_id={c.chunk_id} document_id={c.document_id} "
        f"document_title={c.document_title}]\n{c.content[:400]}"
        for c in passages
    )
    prompt = CONFLICT_DETECTOR_PROMPT.format(question=query, evidence=evidence)
    response = await llm.complete_json(prompt, temperature=0.0)
    raw_conflicts = response.get("conflicts") or []

    known_ids = {c.chunk_id for c in passages}
    conflicts: list[Conflict] = []
    for item in raw_conflicts[:4]:
        try:
            a, b = str(item["a"]), str(item["b"])
        except (KeyError, TypeError):
            continue
        if a not in known_ids or b not in known_ids or a == b:
            continue
        conflicts.append(
            Conflict(a_chunk_id=a, b_chunk_id=b, topic=str(item.get("topic", "the question"))[:120])
        )
    return conflicts


def build_conflict_answer(conflicts: list[Conflict], chunk_by_id: dict[str, ScoredChunk]) -> str:
    """Deterministic conflict report with markers for both sides of each conflict."""
    lines = [
        f"{CONFLICT_ANSWER_PREFIX} on this question, so I will not pick one "
        "silently - please confirm which source is authoritative."
    ]
    for conflict in conflicts:
        a = chunk_by_id.get(conflict.a_chunk_id)
        b = chunk_by_id.get(conflict.b_chunk_id)
        if a is None or b is None:
            continue
        lines.append(
            f"On {conflict.topic}: {a.document_title} states {a.content[:200].strip()} "
            f"[1], while {b.document_title} states {b.content[:200].strip()} [2]."
        )
    return "\n".join(lines)


# --- deterministic fallback (used by the mock judge and as a sanity screen) ---

NumericPattern = tuple[str, re.Pattern[str]]
_NUMERIC_PATTERNS: list[NumericPattern] = [
    ("days per week", re.compile(r"(\d+)\s+days?\s+per\s+week", re.IGNORECASE)),
    ("days per year", re.compile(r"(\d+)\s+days?\s+per\s+year", re.IGNORECASE)),
    (
        "dollar amount per period",
        re.compile(r"\$(\d+)\s*(?:per\s+|/)\s*(?:day|month|week|year)", re.IGNORECASE),
    ),
    ("weeks of leave", re.compile(r"(\d+)\s+weeks?\s+of\s+(?:paid\s+)?leave", re.IGNORECASE)),
    ("percentage", re.compile(r"(\d+)\s*%", re.IGNORECASE)),
]


def heuristic_conflicts(chunks: list[ScoredChunk]) -> list[Conflict]:
    """Number-and-unit heuristic: the same unit pattern with different values
    in different documents is a conflict.

    Used by the mock LLM judge (deterministic offline evaluation) and
    available as a cheap pre-screen. Two passages from one document never
    conflict; identical values never conflict.
    """
    by_doc: dict[str, ScoredChunk] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, chunk)

    conflicts: list[Conflict] = []
    for topic, pattern in _NUMERIC_PATTERNS:
        hits: list[tuple[str, str]] = []  # (value, chunk_id)
        for chunk in by_doc.values():
            for match in pattern.finditer(chunk.content):
                hits.append((match.group(1), chunk.chunk_id))
        for i, (value_a, chunk_a) in enumerate(hits):
            for value_b, chunk_b in hits[i + 1 :]:
                if value_a != value_b and chunk_a != chunk_b:
                    conflicts.append(Conflict(a_chunk_id=chunk_a, b_chunk_id=chunk_b, topic=topic))
    return conflicts[:4]
