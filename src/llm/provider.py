"""LLM provider abstraction — vendor-agnostic.

Use this everywhere instead of `openai` or `anthropic` directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from apps.api.app.core.config import settings


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str


class LLMProvider(Protocol):
    """Abstract LLM provider."""

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> LLMResponse: ...

    async def complete_json(self, prompt: str, *, temperature: float = 0.0) -> dict: ...


class BaseLLMProvider:
    """Base class providing default implementation of complete_json."""

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def complete_json(self, prompt: str, *, temperature: float = 0.0) -> dict:
        """Convenience: complete and parse as JSON."""
        response = await self.complete(prompt, temperature=temperature, max_tokens=2048)
        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re

            match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", response.text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise


# --- Price table (USD per 1k tokens) ---
# Update this when models or prices change.
PRICE_TABLE = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
}


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    prices = PRICE_TABLE.get(model)
    if not prices:
        return 0.0
    return (tokens_in / 1000.0) * prices["input"] + (tokens_out / 1000.0) * prices["output"]


class _OpenAIProvider(BaseLLMProvider):
    """OpenAI implementation."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        )
        text = response.choices[0].message.content or ""
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=compute_cost(self._model, tokens_in, tokens_out),
            model=self._model,
        )


class _AnthropicProvider(BaseLLMProvider):
    """Anthropic implementation."""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022") -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = model

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        response = await self._client.messages.create(  # type: ignore
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text if response.content and hasattr(response.content[0], "text") else ""  # type: ignore
        tokens_in = response.usage.input_tokens
        tokens_out = response.usage.output_tokens
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=compute_cost(self._model, tokens_in, tokens_out),
            model=self._model,
        )


class _MockLLMProvider(BaseLLMProvider):
    """Mock LLM provider used when a test API key (e.g. sk-test) is supplied."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self._model = model

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        prompt_lower = prompt.lower()
        if "query classifier" in prompt_lower:
            text = json.dumps(
                {"class": "simple_factual", "confidence": 1.0, "rationale": "Factual query"}
            )
        elif "planner" in prompt_lower:
            # Query-driven deterministic plan: search_documents with the
            # actual query as sub_question (a fixed plan would make every
            # agent-path evaluation measure the wrong retrieval).
            import re as _re3

            qm = _re3.search(r"Query: (.+)$", prompt, _re3.MULTILINE)
            sub_question = qm.group(1).strip() if qm else "remote work policy"
            text = json.dumps(
                {
                    "steps": [
                        {
                            "sub_question": sub_question,
                            "tool": "search_documents",
                            "tool_args": {},
                        }
                    ],
                    "rationale": "Search relevant documents",
                }
            )
        elif "evidence sufficiency" in prompt_lower:
            # Content-aware deterministic judge (mock mode must be able to
            # say 'insufficient' for corpus-missing queries, otherwise the
            # harness cannot measure abstention behavior):
            # sufficient iff any evidence line contains >= 2 significant
            # query terms (>= 1 when the query is short).
            import re as _re

            stop_words = {
                "the",
                "a",
                "an",
                "of",
                "is",
                "are",
                "our",
                "we",
                "what",
                "how",
                "does",
                "do",
                "in",
                "to",
                "for",
                "and",
                "with",
                "by",
                "on",
                "at",
            }
            question = ""
            m = _re.search(r"QUESTION:\s*(.+?)\nEVIDENCE:", prompt, _re.DOTALL)
            if m:
                question = m.group(1)
            evidence_lines = [
                line[2:].strip() for line in prompt.splitlines() if line.strip().startswith("- ")
            ]
            q_terms = {
                t for t in _re.findall(r"[a-z0-9]+", question.lower()) if t not in stop_words
            }
            need = 1 if len(q_terms) <= 2 else 2
            sufficient = (
                any(
                    len(q_terms & set(_re.findall(r"[a-z0-9]+", ev.lower()))) >= need
                    for ev in evidence_lines
                )
                if q_terms
                else bool(evidence_lines)
            )
            text = json.dumps({"sufficient": sufficient, "reason": "deterministic mock judge"})
        elif "citation correctness" in prompt_lower:
            text = json.dumps({"correctness": 1.0, "issues": []})
        elif "citation verifier" in prompt_lower:
            import re

            chunk_ids = re.findall(r"\[chunk_id=([^\]]+)\]", prompt)
            # Cross-product (claim_index x chunk_id) so any strict lookup of
            # (i, chunk) with i < 8 succeeds - the mock never withholds.
            results = [
                {"claim_index": i, "chunk_id": cid, "supported": True}
                for i in range(8)
                for cid in chunk_ids
            ]
            text = json.dumps({"results": results})
        elif "hallucination" in prompt_lower:
            text = json.dumps({"unsupported_claims": [], "rate": 0.0})
        elif "memory extractor" in prompt_lower:
            text = json.dumps({"memories": []})
        elif "prompt injection" in prompt_lower:
            text = json.dumps({"is_injection": False, "confidence": 0.0, "reason": "benign"})
        else:
            # Default branch = the GENERATOR. Behaviorally realistic mock:
            # extractive summary of the top <retrieved_document> block
            # (first two sentences) with a [1] marker, so end-to-end
            # evaluation under mock mode measures retrieval quality
            # through a deterministic extractive generator.
            import re as _re2

            m = _re2.search(
                r'<retrieved_document index="1"[^>]*>\n(.*?)\n</retrieved_document>',
                prompt,
                _re2.DOTALL,
            )
            if m:
                body = m.group(1).strip()
                sentences = _re2.split(r"(?<=[.!?])\s+", body)
                text = " ".join(sentences[:3]).strip()
                if text and not text.endswith((".", "!", "?")):
                    text += "."
                text = f"{text} [1]"
            else:
                text = (
                    "Employees are eligible to work remotely up to 3 days per week "
                    "according to the company policy [1]."
                )

        tokens_in = len(prompt.split())
        tokens_out = len(text.split())
        return LLMResponse(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=compute_cost(self._model, tokens_in, tokens_out),
            model=self._model,
        )


_llm: Any = None


def get_llm_provider() -> Any:
    """Singleton accessor."""
    global _llm
    if _llm is None:
        if settings.openai_api_key.startswith("sk-test"):
            _llm = _MockLLMProvider(model=settings.openai_default_model)
        elif settings.anthropic_api_key and settings.openai_default_model.startswith("claude"):
            _llm = _AnthropicProvider(model=settings.anthropic_default_model)
        else:
            _llm = _OpenAIProvider(model=settings.openai_default_model)
    return _llm
