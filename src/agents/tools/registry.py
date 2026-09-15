"""Tool registry — tools the agent can call."""

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

    # Permission check
    if tool.permission is not None and tool.permission not in getattr(
        user, "permissions", frozenset()
    ):
        raise PermissionError(f"User lacks required permission: {tool.permission}")

    # Schema validation
    _validate_args(args, tool.schema)

    # Execute
    return await tool.func(
        sub_question=sub_question,
        user=user,
        session=session,
        retrieval_strategy=retrieval_strategy,
        top_k=top_k,
        **args,
    )


def _validate_args(args: dict, schema: dict) -> None:
    """Basic JSON-schema-like validation. Replace with `jsonschema.validate` in prod."""
    required = schema.get("required", [])
    for req in required:
        if req not in args:
            raise ValueError(f"Missing required arg: {req}")

    properties = schema.get("properties", {})
    for key, value in args.items():
        if key not in properties:
            raise ValueError(f"Unknown arg: {key}")
        expected_type = properties[key].get("type")
        if expected_type == "string" and not isinstance(value, str):
            raise ValueError(f"Arg {key} must be string")
        if expected_type == "integer" and not isinstance(value, int):
            raise ValueError(f"Arg {key} must be integer")
        if expected_type == "array" and not isinstance(value, list):
            raise ValueError(f"Arg {key} must be array")
