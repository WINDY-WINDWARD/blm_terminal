"""Tool argument sanitising for the AI chat agent.

Models occasionally decorate tool calls with keys the schema never declared,
for example a ``reason`` string or a bare ``_``. Passing those straight into
the Python tool raised TypeError and failed the whole call.
"""

from app.services.ai_chat_service import _sanitize_tool_args


def _tool(symbol: str, exchange: str = "NSE"):
    return {"symbol": symbol, "exchange": exchange}


def _tool_flexible(symbol: str, **kwargs):
    return {"symbol": symbol, **kwargs}


def test_drops_undeclared_reason_argument():
    assert _sanitize_tool_args("t", _tool, {"symbol": "X", "reason": "why"}) == {
        "symbol": "X"
    }


def test_drops_bare_underscore_argument():
    assert _sanitize_tool_args("t", _tool, {"_": "noop"}) == {}


def test_keeps_declared_arguments():
    args = {"symbol": "X", "exchange": "BSE"}
    assert _sanitize_tool_args("t", _tool, args) == args


def test_passes_everything_through_for_kwargs_tool():
    args = {"symbol": "X", "reason": "why"}
    assert _sanitize_tool_args("t", _tool_flexible, args) == args


def test_non_dict_arguments_become_empty():
    assert _sanitize_tool_args("t", _tool, None) == {}


def test_no_argument_tool_ignores_extras():
    def no_args():
        return 1

    assert _sanitize_tool_args("t", no_args, {"reason": "why"}) == {}
