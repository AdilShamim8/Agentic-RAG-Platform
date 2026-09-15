"""Failure handler — converts Failure enum values to user-facing messages."""

from __future__ import annotations

from src.core.failures import Failure, user_message


def handle_failure(failure: Failure) -> str:
    """Return the user-facing message for a failure."""
    return user_message(failure)
