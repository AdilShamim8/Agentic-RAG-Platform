# Agentic RAG vs. Pipeline RAG

## 1. Architectural Comparison: Static Pipelines vs. Autonomous State Machines

Traditional RAG systems are built as **linear pipelines**: every query—regardless of whether it is a single-fact lookup or a 4-part multi-hop comparative audit—traverses the exact same rigid sequence (`Embed` $\rightarrow$ `Retrieve` $\rightarrow$ `Generate`).

**Agentic RAG** replaces static execution with a **deterministic state machine** capable of:
1. Dynamic query decomposition and multi-step planning.
2. Tool selection and iterative evidence gathering.
3. Self-reflection, evidence sufficiency checks, and back-tracking.
4. Post-generation citation validation and safe abstention.

```
Linear Pipeline RAG:
[Query] ──► [Embed] ──► [Retrieve Top 5] ──► [LLM Generator] ──► [Answer]
* Fails on multi-hop questions requiring facts from separate documents.
* Cannot detect when retrieved evidence is insufficient.

Agentic RAG (State Machine):
                                   ┌──────────────────────┐
                                   │      [1] START       │
                                   └──────────┬───────────┘
                                              ▼
                                 [2] INTENT CLASSIFICATION
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
               (Unsupported)                                   (Valid Query)
                      │                                               │
             Immediate Abstention                                     ▼
                                                                [3] PLANNING
                                                              (Decompose Query)
                                                                      │
                                                ┌─────────────────────┴─────────────────────┐
                                                ▼                                           ▲
                                         [4] TOOL_CALL                                      │
                                       (Execute Search)                                     │ (Insufficient
                                                │                                           │  Evidence &
                                                ▼                                           │  Budget Remains)
                                          [5] RETRIEVE                                      │
                                       (Hybrid RRF Search)                                  │
                                                │                                           │
                                                ▼                                           │
                                          [6] RERANK                                        │
                                       (Cross-Encoder)                                      │
                                                │                                           │
                                                ▼                                           │
                                    [7] EVIDENCE_VALIDATION ────────────────────────────────┘
                                                │
                                                ▼ (Sufficient)
                                        [8] GENERATION
                                    (Draft Answer with [N])
                                                │
                                                ▼
                                    [9] CITATION_VALIDATION
                                                │
                                ┌───────────────┴───────────────┐
                                ▼                               ▼
                           (Verified)                 (Hallucination Failed)
                                │                               │
                                ▼                               ▼
                            [10] END                       [11] FAILED
                      (Return Grounded Answer)        (Safe Structured Refusal)
```

---

## 2. Dynamic Routing: The Classifier

Implemented in [`src/agents/classifier.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/classifier.py), incoming queries are categorized to select the optimal computational path:

| Intent Category | Query Characteristic | Execution Path | Token & Latency Cost |
| :--- | :--- | :--- | :--- |
| **`simple_factual`** | Single-hop factual question ("What is the 401k match?") | **Bypasses Planner**: Direct single-shot hybrid retrieval | Lowest (1 LLM call, ~1.2s) |
| **`comparative`** | Cross-document entity comparison | Full agent loop with multi-entity search | Moderate (3 LLM calls, ~2.5s) |
| **`temporal`** | Effective date or version-sensitive queries | Directs tool to `search_by_date` or `get_document_versions` | Moderate (~2.5s) |
| **`multi_hop`** | Requires chained deductive reasoning | Full agent loop with iterative sub-queries | High (4-6 LLM calls, ~3.5s) |
| **`analytical`** | Broad organizational synthesis | Full agent loop with cross-department retrieval | High (~4.0s) |
| **`unsupported`** | Question outside corporate domain | **Immediate Abstention**: Zero document retrieval | Zero retrieval cost (~300ms) |

---

## 3. The State Machine Specification

Defined in [`src/agents/state.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/state.py), `AgentState` is an immutable, type-safe data model tracking the trajectory of each turn:

```python
class AgentStateName(StrEnum):
    START = "start"
    INTENT_CLASSIFICATION = "intent_classification"
    PLANNING = "planning"
    TOOL_CALL = "tool_call"
    RETRIEVE = "retrieve"
    RERANK = "rerank"
    EVIDENCE_VALIDATION = "evidence_validation"
    GENERATION = "generation"
    CITATION_VALIDATION = "citation_validation"
    END = "end"
    FAILED = "failed"
```

### State Transition Logic
1. **`PLANNING`**: The LLM planner decomposes complex multi-part queries into an array of sub-questions with assigned tools:
   ```json
   [
     {"step": 1, "sub_question": "What is the core budget for Project Alpha?", "tool": "search_documents", "args": {"query": "Project Alpha budget 2024"}},
     {"step": 2, "sub_question": "What were the reported cost overruns?", "tool": "search_documents", "args": {"query": "Project Alpha cost overruns Q2"}}
   ]
   ```
2. **`EVIDENCE_VALIDATION`**: Handled in [`src/agents/evidence_validator.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/evidence_validator.py). A dedicated LLM-judge reviews the aggregated pool of retrieved chunks against the sub-questions. If information is missing and the step budget allows, the orchestrator triggers an additional targeted `TOOL_CALL`.
3. **`CITATION_VALIDATION`**: Handled in [`src/agents/citation_validator.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/citation_validator.py). Validates that every citation marker (`[1]`, `[2]`) in the drafted answer is factually supported by its linked chunk. If all citations fail validation, the answer is withheld under `HALLUCINATION_DETECTED`.

---

## 4. Hard Termination Conditions & Loop Detection

Autonomous agents without strict termination bounds risk infinite recursion and runaway inference costs. The platform enforces four deterministic termination guards:

| Termination Guard | Parameter Limit | Enforcement Mechanism | Failure Action |
| :--- | :--- | :--- | :--- |
| **Max Steps** | `max_steps = 8` | Checked in `AgentState.can_continue()` | Abort loop $\rightarrow$ synthesize best-effort answer with available evidence. |
| **Max Tool Calls** | `max_tool_calls = 10` | Checked in `AgentState.can_continue()` | Abort tool execution $\rightarrow$ proceed directly to generation. |
| **Global Timeout** | `global_timeout_s = 30` | Enforced via Python `asyncio.timeout(30)` | Cancel active coroutines $\rightarrow$ return safe timeout refusal. |
| **Loop Detection** | 2 consecutive identical calls | Evaluated in `AgentState.is_looping()` | Abort loop with `Failure(code="AGENT_LOOP")`. |

### The SHA-256 Loop Detection Algorithm
Implemented in [`src/agents/state.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/agents/state.py):
1. On each tool call, the tool name and its arguments dictionary are serialized into canonical sorted JSON.
2. A truncated SHA-256 hash is computed:
   ```python
   def _hash_args(args: dict) -> str:
       canonical = json.dumps(args, sort_keys=True, default=str)
       return hashlib.sha256(canonical.encode()).hexdigest()[:16]
   ```
3. `is_looping()` inspects the last two entries in `tool_call_history`. If both record the exact same tool and argument hash, the state machine detects an unresolvable reasoning cycle and terminates execution immediately.

---

## 5. Architectural Decision: Custom State Machine vs. LangGraph (ADR-004)

| Feature | Custom Python State Machine (Our Choice) | LangGraph / External Frameworks |
| :--- | :--- | :--- |
| **Code Footprint** | ~200 lines of explicit, typed Python | Heavy multi-package external dependency |
| **Debuggability** | Standard Python stack traces, straightforward breakpoints | Complex abstraction layers, graph compilation |
| **Observability** | Direct 1:1 mapping to OpenTelemetry spans and traces | Requires framework-specific tracing adapters |
| **State Mutability** | Explicit dataclass with clear ownership boundaries | Dynamic graph state dictionary |
| **Latency Overhead** | Sub-millisecond state transition overhead | Multi-millisecond graph evaluation overhead |

**Conclusion**: For enterprise RAG applications with deterministic failure conditions and strict compliance requirements, an explicit in-house state machine provides greater reliability, security, and performance.

---

## 6. Production Checklist

- [x] Fast intent classifier routing simple queries to single-pass retrieval.
- [x] Multi-hop query decomposition in the LLM planner.
- [x] Evidence sufficiency gateway triggering targeted follow-up retrieval.
- [x] Post-generation citation validation preventing hallucinated claims.
- [x] Hard boundaries on steps (8), tool calls (10), and timeout (30s).
- [x] Cryptographic SHA-256 argument hashing for loop detection.
