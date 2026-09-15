"""Logging setup — structlog with PII redaction."""

from __future__ import annotations

import logging
import re
from typing import Any

import structlog

# Patterns to redact from logs
REDACT_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-REDACTED"),
    (re.compile(r"hf_[a-zA-Z0-9]{20,}"), "hf_REDACTED"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AKIA_REDACTED"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "ghp_REDACTED"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "EMAIL_REDACTED"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN_REDACTED"),
    (re.compile(r"\b\d{16}\b"), "CC_REDACTED"),
]


def _redact(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Processor that redacts known sensitive patterns from all log values."""

    def _redact_value(v: Any) -> Any:
        if isinstance(v, str):
            for pat, repl in REDACT_PATTERNS:
                v = pat.sub(repl, v)
            return v
        if isinstance(v, dict):
            return {k: _redact_value(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_redact_value(x) for x in v]
        return v

    return {k: _redact_value(v) for k, v in event_dict.items()}


def setup_logging(*, log_level: str = "INFO") -> None:
    """Call once at app startup."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
