"""Tool registry — tools the agent can call.

Validation contract (replaces the old 3-type check):
- required keys, unknown keys rejected (additionalProperties: false semantics)
- types: string / integer / number / boolean / array / object (bool is NOT
  an integer, unlike Python's isinstance)
- enum membership; numeric minimum/maximum; string minLength/maxLength
- array items validated against the element schema
- nested object properties/required validated recursively

Every tool call is validated BEFORE execution; planner output that fails
validation is rejected with a descriptive error (and the planner prompt
now documents the schemas, so well-behaved planners produce valid args).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.retrieval.types import ScoredChunk


@dataclass
class ToolResult:
    chunks: list[ScoredChunk]
    cost_usd: float = 0.0
    metadata: dict | None = None


ToolFunc = Callable[..., Awaitable[ToolResult]]

_REGISTRY: dict[str, ToolDef] = {}


@dataclass
class ToolDef:
    name: str
    description: str
    schema: dict
    func: ToolFunc
    permission: str | None = None  # required permission slug, None = any authenticated user


def register_tool(
    *, name: str, description: str, schema: dict, permission: str | None = None
) -> Callable[[ToolFunc], ToolFunc]:
    """Decorator to register a tool."""

    def decorator(func: ToolFunc) -> ToolFunc:
        _REGISTRY[name] = ToolDef(
            name=name, description=description, schema=schema, func=func, permission=permission
        )
        return func

    return decorator


def list_tools() -> list[ToolDef]:
    return list(_REGISTRY.values())


def get_tool(name: str) -> ToolDef | None:
    return _REGISTRY.get(name)


def validate_tool_args(tool_name: str, args: dict) -> None:
    """Public validation entry point (also used by tests and sanitizers)."""
    tool = get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")
    _validate(args, tool.schema, path=f"args of {tool_name}")


async def execute_tool(
    *,
    tool_name: str,
    args: dict,
    sub_question: str,
    user: Any,
    session: Any,
    retrieval_strategy: str,
    top_k: int | None,
) -> ToolResult:
    """Execute a tool by name. Validates args against schema and checks permissions."""
    tool = get_tool(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    # Permission check (server-side, independent of the planner)
    if tool.permission is not None and tool.permission not in getattr(
        user, "permissions", frozenset()
    ):
        raise PermissionError(f"User lacks required permission: {tool.permission}")

    # Schema validation
    _validate(args, tool.schema, path=f"args of {tool_name}")

    # Execute
    return await tool.func(
        sub_question=sub_question,
        user=user,
        session=session,
        retrieval_strategy=retrieval_strategy,
        top_k=top_k,
        **args,
    )


_TYPE_CHECKERS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: type(v) is int,  # bool is NOT an integer
    "number": lambda v: type(v) in (int, float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _validate(value: Any, schema: dict, path: str) -> None:
    """Validate a value against a JSON-schema subset (see module docstring)."""
    if not isinstance(schema, dict):
        return  # no schema information -> nothing to check

    expected_type = schema.get("type")
    if expected_type is not None:
        checker = _TYPE_CHECKERS.get(str(expected_type))
        if checker is None:
            raise ValueError(f"{path}: unsupported schema type {expected_type!r}")
        if not checker(value):
            raise ValueError(f"{path} must be of type {expected_type}")

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ValueError(f"{path} must be one of {enum}")

    if isinstance(value, bool):
        pass  # bool validated by its own type checkers above
    elif isinstance(value, (int, float)):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{path} must be <= {maximum}")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < min_length:
            raise ValueError(f"{path} must have length >= {min_length}")
        if max_length is not None and len(value) > max_length:
            raise ValueError(f"{path} must have length <= {max_length}")

    if isinstance(value, list):
        items_schema = schema.get("items")
        if items_schema is not None:
            for i, item in enumerate(value):
                _validate(item, items_schema, path=f"{path}[{i}]")

    if isinstance(value, dict):
        properties: dict = schema.get("properties", {}) or {}
        required: list = schema.get("required", []) or []
        for key in required:
            if key not in value:
                raise ValueError(f"{path} is missing required key {key!r}")
        for key in value:
            if key not in properties:
                raise ValueError(f"{path} has unknown key {key!r}")
            _validate(value[key], properties.get(key, {}), path=f"{path}.{key}")
