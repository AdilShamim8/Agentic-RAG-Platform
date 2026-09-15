"""Explicit failure states — every failure has a name and a user-friendly message.

Never silently swallow errors. Map every failure to one of these enum values.
"""

from __future__ import annotations

from enum import StrEnum


class Failure(StrEnum):
    """All known failure modes. Add new ones here, never reuse a value."""

    NO_DOCUMENTS = "no_documents"
    IRRELEVANT_DOCUMENTS = "irrelevant_documents"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONFLICTING_SOURCES = "conflicting_sources"
    OUTDATED_SOURCES = "outdated_sources"
    TOOL_FAILURE = "tool_failure"
    DB_FAILURE = "db_failure"
    EMBEDDING_FAILURE = "embedding_failure"
    LLM_TIMEOUT = "llm_timeout"
    RATE_LIMIT = "rate_limit"
    MALFORMED_RESPONSE = "malformed_response"
    CORRUPTED_DOCUMENT = "corrupted_document"
    RETRIEVAL_TIMEOUT = "retrieval_timeout"
    AGENT_LOOP = "agent_loop"
    HALLUCINATION_DETECTED = "hallucination_detected"
    CITATION_MISMATCH = "citation_mismatch"


USER_MESSAGES: dict[Failure, str] = {
    Failure.NO_DOCUMENTS: "I couldn't find any documents matching your question.",
    Failure.IRRELEVANT_DOCUMENTS: "The documents I found don't seem relevant to your question.",
    Failure.INSUFFICIENT_EVIDENCE: "I don't have enough evidence to answer this confidently.",
    Failure.CONFLICTING_SOURCES: "I found conflicting information in the sources and cannot give a definitive answer.",
    Failure.OUTDATED_SOURCES: "The only sources I found are outdated.",
    Failure.TOOL_FAILURE: "A required tool failed. Please try again.",
    Failure.DB_FAILURE: "The database is temporarily unavailable. Please try again.",
    Failure.EMBEDDING_FAILURE: "I couldn't process your query. Please rephrase it.",
    Failure.LLM_TIMEOUT: "The model is taking too long. Please try again.",
    Failure.RATE_LIMIT: "We're being rate-limited by the model provider. Please try again in a moment.",
    Failure.MALFORMED_RESPONSE: "I received a malformed response from the model. Please try again.",
    Failure.CORRUPTED_DOCUMENT: "One of the source documents appears corrupted.",
    Failure.RETRIEVAL_TIMEOUT: "Retrieval took too long. Please try a simpler query.",
    Failure.AGENT_LOOP: "I'm having trouble reasoning through this. Could you rephrase?",
    Failure.HALLUCINATION_DETECTED: "I generated an answer I cannot verify. Withholding response.",
    Failure.CITATION_MISMATCH: "I couldn't verify my citations. Withholding response.",
}


def user_message(failure: Failure) -> str:
    return USER_MESSAGES.get(failure, "Something went wrong. Please try again.")
