"""Tool registry validation contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from src.agents import tools as tools_pkg  # noqa: F401 - ensures registration side effect
from src.agents.tools import get_tool, list_tools, register_tool
from src.agents.tools.registry import validate_tool_args


@pytest.fixture(autouse=True)
def _tools_registered():
    """The package import registers built-ins; ensure they are present."""
    assert {"search_documents", "search_by_date", "memory_search", "get_document_versions"} <= {
        t.name for t in list_tools()
    }
    yield


@contextmanager
def _register(schema: dict) -> Iterator[str]:
    """Register a throwaway tool with the given schema under a unique name."""

    async def _func(**_kwargs):
        from src.agents.tools.registry import ToolResult

        return ToolResult(chunks=[])

    register_tool(
        name="_schema_probe",
        description="probe",
        schema=schema,
    )(  # type: ignore[arg-type]
        _func
    )
    try:
        yield "_schema_probe"
    finally:
        from src.agents.tools.registry import _REGISTRY

        _REGISTRY.pop("_schema_probe", None)


def test_validate_unknown_tool_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        validate_tool_args("no_such_tool", {})


def test_validate_required_and_unknown_keys() -> None:
    schema = {
        "type": "object",
        "properties": {"document_id": {"type": "string", "minLength": 1}},
        "required": ["document_id"],
    }
    with _register(schema) as name:
        with pytest.raises(ValueError, match="missing required key 'document_id'"):
            validate_tool_args(name, {})
        with pytest.raises(ValueError, match="unknown key"):
            validate_tool_args(name, {"document_id": "x", "extra": 1})
        validate_tool_args(name, {"document_id": "x"})  # valid


def test_validate_types_bool_is_not_integer() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "b": {"type": "boolean"}}}
    with _register(schema) as name:
        with pytest.raises(ValueError, match="must be of type integer"):
            validate_tool_args(name, {"n": True, "b": True})
        with pytest.raises(ValueError, match="must be of type boolean"):
            validate_tool_args(name, {"n": 3, "b": "yes"})
        validate_tool_args(name, {"n": 3, "b": False})


def test_validate_enum_and_bounds() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["fast", "slow"]},
            "count": {"type": "integer", "minimum": 1, "maximum": 10},
        },
    }
    with _register(schema) as name:
        with pytest.raises(ValueError, match="one of"):
            validate_tool_args(name, {"mode": "turbo", "count": 5})
        with pytest.raises(ValueError, match=">= 1"):
            validate_tool_args(name, {"mode": "fast", "count": 0})
        with pytest.raises(ValueError, match="<= 10"):
            validate_tool_args(name, {"mode": "fast", "count": 11})
        validate_tool_args(name, {"mode": "slow", "count": 10})


def test_validate_string_length() -> None:
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string", "minLength": 2, "maxLength": 5}},
    }
    with _register(schema) as name:
        with pytest.raises(ValueError, match="length >= 2"):
            validate_tool_args(name, {"q": "x"})
        with pytest.raises(ValueError, match="length <= 5"):
            validate_tool_args(name, {"q": "toolongvalue"})
        validate_tool_args(name, {"q": "ok"})


def test_validate_array_items_and_nested_objects() -> None:
    schema = {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "filters": {
                "type": "object",
                "properties": {"department": {"type": "string"}},
                "required": [],
            },
        },
    }
    with _register(schema) as name:
        with pytest.raises(ValueError, match=r"tags\[1\] must be of type string"):
            validate_tool_args(name, {"tags": ["a", 2]})
        with pytest.raises(ValueError, match="filters has unknown key"):
            validate_tool_args(name, {"filters": {"nope": "x"}})
        validate_tool_args(name, {"tags": ["a", "b"], "filters": {"department": "hr"}})


def test_get_document_versions_schema_requires_id() -> None:
    tool = get_tool("get_document_versions")
    assert tool is not None
    with pytest.raises(ValueError, match="document_id"):
        validate_tool_args("get_document_versions", {})
    validate_tool_args("get_document_versions", {"document_id": "abc"})
