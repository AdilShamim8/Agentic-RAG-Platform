# Citations

> How this project builds, verifies, and exposes citations so users can trace every claim back to its source document.

## Concept

A **citation** is a mapping from a specific claim in the generated answer to the exact chunk in the document corpus that supports that claim. The LLM is instructed to embed inline markers (`[1]`, `[2]`, …) in its answer; the citation builder then resolves each marker to a chunk, and the citation validator verifies that the chunk actually supports the claim.

The goal is not just to show sources — it is to guarantee that every sentence in the answer is traceable and verifiable by the user.

## Why it exists

LLMs are fluent and confident. They can produce answers that sound correct but are not supported by any retrieved document. Without citation verification:

- A user has no way to distinguish a grounded claim from a hallucination.
- The system cannot detect when the LLM "makes up" a reference to a non-existent document.
- Audits and compliance checks are impossible.

Citation verification converts the LLM from a trust-me oracle into a transparent, auditable system.

## How it works (in this project)

### Step 1 — Generation with inline markers

The generator LLM receives the retrieved evidence chunks and is instructed via the system prompt to:

1. Answer only from the provided evidence.
2. Mark every claim with `[N]` where N is the 1-indexed position of the supporting chunk in the context.
3. If a claim cannot be attributed to any chunk, omit the claim.

### Step 2 — Citation building

`src/agents/citation_validator.py` parses the generated answer to extract all `[N]` markers. For each marker, it maps the index back to the original chunk object (document ID, chunk ID, text excerpt, page number, source URL).

### Step 3 — Citation validation (LLM-judge)

For each (claim, chunk) pair, an LLM-judge determines whether the chunk genuinely supports the claim. The judge uses a strict prompt:

```
Given this claim: "<claim>"
And this evidence: "<chunk_text>"
Does the evidence directly support the claim? Answer YES or NO only.
```

If a citation is not supported, it is flagged. If **all** citations are flagged as unsupported, the answer is withheld and the response becomes `HALLUCINATION_DETECTED`.

### Step 4 — Persistence

Verified citations are written to the `citations` table (linked to the `messages` row) and returned to the frontend in the `QueryResponse`.

```
User → API → Agent → Generator (with [N] markers)
                   → CitationBuilder (resolve markers → chunks)
                   → CitationValidator (LLM-judge per citation)
                   → Save to citations table
                   → QueryResponse { answer, citations: [{chunk_id, text, document_title, page}] }
```

## Where it appears in the code

| File | Purpose |
| ---- | ------- |
| `src/agents/citation_validator.py` | Parses markers, resolves chunks, runs LLM-judge |
| `src/agents/generator.py` | Instructs the LLM to use `[N]` markers |
| `prompts/v1/generation.md` | System prompt that enforces citation markers |
| `prompts/v1/citation_validation.md` | Prompt for the LLM-judge |
| `alembic/versions/` | `citations` table schema migration |
| `apps/api/app/models/` | `Citation` SQLAlchemy model |

## Trade-offs

### Citation markers vs. post-hoc attribution

- **Markers approach** (this project): LLM is told upfront to mark claims. Straightforward; fails when the LLM ignores the instruction.
- **Post-hoc attribution**: generate freely, then attribute. More complex; produces cleaner prose but requires semantic matching between claims and chunks.

We use the markers approach because it is simpler to implement and debug, and the LLM-judge validation catches cases where the LLM faked a marker.

### LLM-judge vs. semantic similarity threshold

- **LLM-judge** (this project): accurate but adds ~$0.0001 per query and ~200ms latency.
- **Semantic similarity**: fast and cheap but misses cases where the chunk is topically related but does not actually support the claim.

We use the LLM-judge because false citations are worse than slow citations.

## Failure modes

| Failure | Description | Mitigation |
| ------- | ----------- | ---------- |
| `HALLUCINATION_DETECTED` | No citation passes validation | Answer withheld; logged for forensics |
| Missing marker | LLM answers without citing | Detected by the citation builder (answer contains 0 markers → warning) |
| Wrong index | LLM writes `[7]` but only 5 chunks exist | Citation builder ignores out-of-range indexes |
| Partial validation failure | Some citations valid, some invalid | Valid citations kept; invalid ones removed from the response |

See `docs/operations/runbook.md` for the `HALLUCINATION_DETECTED` runbook.

## Further reading

- Gao et al., "RARR: Researching and Revising What Language Models Say, Using Language Models" (2023) — a related approach to post-hoc attribution.
- Nakano et al., "WebGPT: Browser-assisted question-answering with human feedback" (2021) — an early example of citation-grounded generation.
- Menick et al., "Teaching language models to support answers with verified quotes" (2022) — DeepMind's approach to cited generation.
