"""Access-aware retrieval — the `access_matches` SQL function and Python helpers.

CRITICAL: This is the single most important security primitive.
Retrieval SQL filters on access_matches() in the WHERE clause, BEFORE the vector search.
"""

from __future__ import annotations

# SQL function definition — applied via migration 0002
ACCESS_MATCHES_SQL = """
CREATE OR REPLACE FUNCTION rag.access_matches(
    policy jsonb,
    user_role text,
    user_projects text[],
    user_id uuid
) RETURNS boolean AS $$
DECLARE
    allowed_roles text[];
    allowed_projects text[];
    allowed_users uuid[];
BEGIN
    -- NULL or empty policy = public (anyone can read)
    IF policy IS NULL OR policy = '{}'::jsonb THEN
        RETURN true;
    END IF;

    allowed_roles := COALESCE(
        (SELECT array_agg(e::text) FROM jsonb_array_elements_text(policy->'roles') e),
        ARRAY[]::text[]
    );
    allowed_projects := COALESCE(
        (SELECT array_agg(e::text) FROM jsonb_array_elements_text(policy->'projects') e),
        ARRAY[]::text[]
    );
    allowed_users := COALESCE(
        (SELECT array_agg(e::uuid) FROM jsonb_array_elements_text(policy->'users') e),
        ARRAY[]::uuid[]
    );

    -- Administrator always has access
    IF user_role = 'administrator' THEN
        RETURN true;
    END IF;

    -- Explicit user allowlist
    IF user_id = ANY(allowed_users) THEN
        RETURN true;
    END IF;

    -- Role-based
    IF user_role = ANY(allowed_roles) THEN
        RETURN true;
    END IF;

    -- Project-based
    IF array_length(allowed_projects, 1) > 0 AND user_projects && allowed_projects THEN
        RETURN true;
    END IF;

    RETURN false;
END;
$$ LANGUAGE plpgsql IMMUTABLE SECURITY DEFINER;
"""


def can_access(
    *, user_role: str, user_projects: frozenset[str], user_id: str, access_policy: dict
) -> bool:
    """Python-side check — used for double-checking after SQL retrieval."""
    if not access_policy:
        return True
    if user_role == "administrator":
        return True
    if user_id in access_policy.get("users", []):
        return True
    if user_role in access_policy.get("roles", []):
        return True
    return bool(set(access_policy.get("projects", [])) & user_projects)
