# Memory Architecture in Agentic RAG

## 1. The Dual-Layer Memory Model

Standard naive RAG systems operate statelessly: each user turn is processed in complete isolation without awareness of prior dialogue or evolving user context. The Agentic RAG Platform implements a dual-layer memory hierarchy:

```
                          User Conversation Turn
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
      Short-Term Memory                       Long-Term Memory
  (Sliding Conversation Window)            (Persistent Knowledge Store)
                 │                                       │
     Last N messages (default: 10)            User preferences, project
      Maintains dialogue context                context, past decisions
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                        Agent Context Synthesis
             (Grounded retrieval + personalized response)
```

| Memory Layer | Storage Table | Scope | Lifecycle | Extraction Method |
| :--- | :--- | :--- | :--- | :--- |
| **Short-Term Memory** | `messages` | Single conversation thread | Ephemeral (session duration) | Direct SQL fetch of last 10 messages |
| **Long-Term Memory** | `memories` | User-wide across all sessions | Persistent with optional TTL | Async LLM extraction + validation judge |

---

## 2. Short-Term Memory: Conversation Sliding Window

Implemented in [`src/memory/short_term.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/memory/short_term.py), short-term memory enables conversational co-reference resolution (e.g., understanding that *"What were its security implications?"* refers to the document discussed in the previous prompt).

- **Sliding Window**: Default $N=10$ message history.
- **Context Injection**: Prior dialogue turns are prepended to the generator prompt under `<conversation_history>` tags.
- **Token Budget Guard**: If conversation history exceeds 2,000 tokens, older turns are truncated while preserving the system prompt and the current turn.

---

## 3. Long-Term Memory: Schema and Taxonomy

Implemented in [`src/memory/long_term.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/memory/long_term.py) and [`apps/api/app/models/memory.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/apps/api/app/models/memory.py), long-term memories are categorized into four distinct functional scopes:

1. **`user_pref`**: Formatting, presentation, and tone preferences.
   - Example: *"User prefers answers formatted as bullet points with code snippets."*
2. **`project_context`**: Domain assignment and active engineering context.
   - Example: *"User is an engineer on the Payments Core infrastructure team."*
3. **`recurring_question`**: Topics of frequent inquiry requiring prioritized retrieval.
   - Example: *"User frequently queries PostgreSQL WAL replication policies."*
4. **`decision`**: Explicit decisions reached in prior conversation turns.
   - Example: *"User chose Docker compose with pgvector rather than Pinecone."*

### PostgreSQL Schema (`memories` table)
```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'extracted', -- 'extracted' | 'user_defined'
    confidence FLOAT NOT NULL DEFAULT 0.5,
    embedding vector(1024),
    expires_at TIMESTAMPTZ,
    superseded_by UUID REFERENCES memories(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX ix_memories_user_id ON memories(user_id);
CREATE INDEX ix_memories_expires_at ON memories(expires_at);
```

---

## 4. Extraction & Conflict Resolution Pipeline

### 4.1 Automatic Extraction
After each completed query turn, the orchestrator triggers background memory extraction using [`src/memory/long_term.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/memory/long_term.py):

```python
async def extract_memories(
    *, question: str, answer: str, user_id: str, session: AsyncSession, llm: LLMProvider | None = None
) -> list[Memory]:
    prompt = MEMORY_EXTRACTION_PROMPT.format(question=question, answer=answer)
    response = await llm.complete_json(prompt, temperature=0.0)
    # Extracts scope, content, confidence, and optional ttl_days
```

The extractor explicitly discards transient chatter, sensitive PII, and facts already documented in organizational chunks.

### 4.2 Conflict Resolution via `superseded_by`
Human preferences change over time. When a user previously preferred *"brief summaries"* but later requests *"detailed step-by-step mathematical walkthroughs"*, a naive memory store generates contradictory instructions.

The platform handles this via an immutable audit trail using the `superseded_by` foreign key:
1. When a new memory is proposed, the system queries existing non-superseded memories under the same `(user_id, scope)`.
2. A conflict detector evaluates semantic contradiction.
3. The existing memory is marked: `conflicting.superseded_by = new_memory.id`.
4. The historical record is preserved for auditability, but permanently excluded from future retrieval queries.

---

## 5. Security & Privacy Guarantees

### 5.1 Strict Multi-Tenant Isolation
Memories are private to individual users. In [`src/memory/retrieval.py`](file:///c:/Users/Adil/Downloads/Agentic-RAG-Platform-main/src/memory/retrieval.py), every query enforces an uncompromising SQL predicate:

```sql
SELECT * FROM memories
WHERE user_id = :current_user_id
  AND deleted_at IS NULL
  AND superseded_by IS NULL
  AND (expires_at IS NULL OR expires_at >= NOW())
ORDER BY created_at DESC
LIMIT :top_k;
```
Under no circumstances can an employee retrieve or synthesize responses based on another employee's memories.

### 5.2 Strict Citation Isolation (ADR-005)
A fundamental design decision was separating `memories` from `document_chunks`. Citations (`[1]`, `[2]`) in generated answers **only** map to authoritative corporate documentation. User memories **never** generate verifiable citations, preventing circular hallucination loops where an LLM treats prior user speculation as verified organizational fact.

---

## 6. Failure Modes and Mitigations

### 6.1 Memory Store Pollution
- **Problem**: Storing low-signal conversational remarks ("I like Python", "It is raining outside").
- **Mitigation**: Confidence threshold gate ($confidence \ge 0.70$), LLM-judge filtering, and a hard quota of 50 active memories per user.

### 6.2 Stale Context Bleed
- **Problem**: Temporary project assignments persisting long after the sprint has concluded.
- **Mitigation**: Scope-based TTL expiration (`ttl_days` set to 30 days for project context, `NULL` for stable user preferences).

---

## 7. Production Checklist

- [x] Short-term sliding window capped at $N=10$ messages with token budget protection.
- [x] Long-term memory stored in dedicated `memories` table with foreign key to `users`.
- [x] Strict user isolation enforced at the SQL layer (`user_id = :user_id`).
- [x] Automated conflict resolution using `superseded_by` pointers.
- [x] Expiration policy evaluation (`expires_at >= NOW()`).
- [x] User-facing CRUD API (`/memory`) providing full user visibility and control.
