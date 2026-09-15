"""Agent state machine.

States:
  START → INTENT_CLASSIFICATION → PLANNING → TOOL_CALL → RETRIEVE → RERANK
       → EVIDENCE_VALIDATION → (INSUFFICIENT_EVIDENCE? → TOOL_CALL again, max N times)
       → GENERATION → CITATION_VALIDATION → (FAILED? → GENERATION again, max M times)
       → END
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.citations.types import CitationResult
from src.core.failures import Failure


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


@dataclass
class AgentState:
    """Mutable state carried through the agent loop."""

    query: str
    user_id: str
    user_role: str
    user_permissions: frozenset[str]
    user_projects: frozenset[str]
    conversation_id: str
    trace_id: str

    current_state: AgentStateName = AgentStateName.START
    steps: int = 0
    tool_calls: int = 0
    tool_call_history: list[dict] = field(default_factory=list)  # for loop detection
    sub_questions: list[str] = field(default_factory=list)
    retrieved_chunks: list[Any] = field(default_factory=list)  # ScoredChunk list
    citations: list[CitationResult] = field(default_factory=list)
    answer: str = ""
    failure: Failure | None = None
    cost_usd: float = 0.0

    # Limits (injected from settings)
    max_steps: int = 8
    max_tool_calls: int = 10
    global_timeout_s: int = 30

    def is_terminal(self) -> bool:
        return self.current_state in {AgentStateName.END, AgentStateName.FAILED}

    def force_terminal(self, *, reason: str, failure: Failure | None = None) -> None:
        self.failure = failure
        self.current_state = AgentStateName.FAILED if failure else AgentStateName.END

    def can_continue(self) -> bool:
        return self.steps < self.max_steps and self.tool_calls < self.max_tool_calls

    def record_tool_call(self, tool: str, args: dict) -> None:
        """Record a tool call and detect loops."""
        args_hash = _hash_args(args)
        self.tool_call_history.append({"tool": tool, "args_hash": args_hash})
        self.tool_calls += 1

    def is_looping(self, tool: str, args: dict) -> bool:
        """True if the same (tool, args_hash) appears in the last 2 tool calls."""
        args_hash = _hash_args(args)
        recent = self.tool_call_history[-2:]
        if len(recent) < 2:
            return False
        return all(c["tool"] == tool and c["args_hash"] == args_hash for c in recent)


def _hash_args(args: dict) -> str:
    """Stable hash of tool args for loop detection."""
    import hashlib
    import json

    canonical = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
