"""Memory policy — what to store, what to skip, when to expire."""

from __future__ import annotations

from datetime import UTC, datetime

# Policy: max memories per user
MAX_MEMORIES_PER_USER = 500

# After this many days, low-confidence memories are auto-expired
LOW_CONFIDENCE_EXPIRY_DAYS = 30


# Triggers eviction when user exceeds MAX_MEMORIES_PER_USER
# Eviction policy: lowest confidence first, expired first, then oldest
def should_evict(memory) -> bool:
    """Return True if a memory should be evicted to make room."""
    if memory.expires_at and memory.expires_at < datetime.now(UTC):
        return True
    return memory.confidence < 0.3
