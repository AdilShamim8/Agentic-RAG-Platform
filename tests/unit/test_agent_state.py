"""Unit tests for agent loop detection."""

from __future__ import annotations

from src.agents.state import AgentState, AgentStateName


def test_state_initial():
    state = AgentState(
        query="test",
        user_id="u1",
        user_role="employee",
        user_permissions=frozenset(),
        user_projects=frozenset(),
        conversation_id="c1",
        trace_id="t1",
    )
    assert state.current_state == AgentStateName.START
    assert not state.is_terminal()
    assert state.can_continue()


def test_state_max_steps():
    state = AgentState(
        query="test",
        user_id="u1",
        user_role="employee",
        user_permissions=frozenset(),
        user_projects=frozenset(),
        conversation_id="c1",
        trace_id="t1",
        max_steps=2,
    )
    state.steps = 2
    assert not state.can_continue()


def test_loop_detection():
    state = AgentState(
        query="test",
        user_id="u1",
        user_role="employee",
        user_permissions=frozenset(),
        user_projects=frozenset(),
        conversation_id="c1",
        trace_id="t1",
    )

    args = {"query": "foo"}
    assert not state.is_looping("search_documents", args)
    state.record_tool_call("search_documents", args)
    state.record_tool_call("search_documents", args)
    assert state.is_looping("search_documents", args)


def test_force_terminal():
    state = AgentState(
        query="test",
        user_id="u1",
        user_role="employee",
        user_permissions=frozenset(),
        user_projects=frozenset(),
        conversation_id="c1",
        trace_id="t1",
    )
    from src.core.failures import Failure

    state.force_terminal(reason="test", failure=Failure.AGENT_LOOP)
    assert state.is_terminal()
    assert state.failure == Failure.AGENT_LOOP
