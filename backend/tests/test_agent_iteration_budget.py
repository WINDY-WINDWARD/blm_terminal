"""Agent loop iteration budget: 60-turn cap, wrap-up warning at 45, wall-clock guard."""

import json
from typing import Any

import pytest

from app.services import llm_provider as lp


def _done_summary() -> dict[str, Any]:
    return {
        "content": "",
        "reasoning": "",
        "finish_reason": "tool_calls",
        "tool_calls_map": {},
        "usage": {},
    }


def _count_warning(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages if m.get("content") == lp._ITERATION_BUDGET_WARNING)


@pytest.fixture
def harness(monkeypatch):
    """Replace the HTTP turn with a fake that always reports one tool call."""
    calls: list[list[dict[str, Any]]] = []

    async def fake_turn(**kwargs):
        # Snapshot the messages: the loop keeps mutating the same list object.
        calls.append([dict(m) for m in kwargs["payload"]["messages"]])
        yield ("done", _done_summary())

    def fake_extract(tool_calls_map, passthrough_thought_signature=False):
        return [], [{"id": "call-1", "name": "noop", "args": {}}], []

    monkeypatch.setattr(lp, "_get_shared_client", lambda: object())
    monkeypatch.setattr(lp, "_run_stream_turn", fake_turn)
    monkeypatch.setattr(lp, "_extract_normalised_tool_calls", fake_extract)
    return calls


async def _executor(_normalised):
    return [], []


async def _collect(calls: list, max_iter: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async for raw in lp._run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-6-luna",
        api_key="test-key",
        tools=[],
        tool_executor=_executor,
        max_iter=max_iter,
        base_url="http://127.0.0.1:8317/v1",
    ):
        events.append(json.loads(raw))
    return events


async def test_warning_injected_once_at_iteration_45(harness):
    events = await _collect(harness, lp._DEFAULT_MAX_ITER)

    assert lp._DEFAULT_MAX_ITER == 60
    assert len(harness) == 60, "the loop should use the full 60-turn budget"

    # No warning before turn 45, exactly one from turn 45 onwards.
    assert _count_warning(harness[43]) == 0
    assert _count_warning(harness[44]) == 1
    assert _count_warning(harness[59]) == 1

    assert events[-1] == {"type": "done"}
    assert events[-2]["type"] == "error"
    assert "60-iteration limit" in events[-2]["message"]


async def test_explicit_low_max_iter_is_unaffected(harness):
    events = await _collect(harness, 1)

    assert len(harness) == 1
    assert _count_warning(harness[0]) == 0
    assert events[-1] == {"type": "done"}
    assert events[-2]["type"] == "error"
    assert "1-iteration limit" in events[-2]["message"]


async def test_wall_clock_guard_ends_loop_before_any_turn(harness, monkeypatch):
    monkeypatch.setattr(lp, "_LOOP_WALL_CLOCK_CAP", -1.0)

    events = await _collect(harness, lp._DEFAULT_MAX_ITER)

    assert harness == [], "the guard must fire before the first HTTP turn"
    assert events == [
        {"type": "error", "message": lp._WALL_CLOCK_EXHAUSTED_MESSAGE},
        {"type": "done"},
    ]
