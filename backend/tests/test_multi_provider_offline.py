"""Offline tests for the multi-provider layer (no network calls)."""

import base64
import json


def _jwt(exp, acct):
    def b64(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

    return (
        b64({"alg": "none"})
        + "."
        + b64({"exp": exp, "https://api.openai.com/auth": {"chatgpt_account_id": acct}})
        + ".sig"
    )


def test_codex_parser_tool_call_turn():
    from app.services.codex_responses import CodexStreamParser

    p = CodexStreamParser()
    frames = [
        json.dumps({"type": "response.output_text.delta", "delta": "Let me check "}),
        json.dumps({"type": "response.output_text.delta", "delta": "that quote."}),
        json.dumps(
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_abc",
                    "call_id": "call_abc",
                    "name": "get_symbol_data",
                    "arguments": "",
                },
            }
        ),
        json.dumps(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 1,
                "delta": '{"sym',
            }
        ),
        json.dumps(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 1,
                "item_id": "fc_abc",
                "delta": 'bol": "RELIANCE"}',
            }
        ),
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "output_index": 1,
                "item_id": "fc_abc",
                "arguments": '{"symbol": "RELIANCE"}',
            }
        ),
        json.dumps(
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_abc",
                    "call_id": "call_abc",
                    "name": "get_symbol_data",
                    "arguments": '{"symbol": "RELIANCE"}',
                },
            }
        ),
        json.dumps({"type": "response.completed", "response": {"status": "completed"}}),
    ]
    events = []
    for f in frames:
        events += p.feed(f)
    assert p.text == "Let me check that quote."
    assert p.saw_terminal and p.status == "completed"
    assert any(e["type"] == "token" for e in events)
    tcs = p.tool_calls()
    assert len(tcs) == 1
    assert tcs[0]["function"]["name"] == "get_symbol_data"
    assert json.loads(tcs[0]["function"]["arguments"]) == {"symbol": "RELIANCE"}


def test_codex_parser_refusal_and_terminal():
    from app.services.codex_responses import CodexStreamParser

    p2 = CodexStreamParser()
    p2.feed(json.dumps({"type": "response.refusal.delta", "delta": "I cannot help"}))
    p2.feed(json.dumps({"type": "response.completed", "response": {"status": "completed"}}))
    assert p2.text == "I cannot help" and p2.saw_terminal

    p3 = CodexStreamParser()
    p3.feed(json.dumps({"type": "response.output_text.delta", "delta": "partial..."}))
    assert not p3.saw_terminal and p3.text == "partial..."

    p4 = CodexStreamParser()
    assert not p4.saw_terminal and p4.tool_calls() == []


def test_codex_request_conversion():
    from app.services.codex_responses import build_responses_payload

    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_top_gainers", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "[...]"},
    ]
    payload = build_responses_payload(
        model="gpt-5.1-codex",
        instructions="sys-prompt",
        messages=msgs,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_top_gainers",
                    "description": "d",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    assert payload["store"] is False and payload["stream"] is True
    types = [i.get("type", i.get("role")) for i in payload["input"]]
    assert types == ["user", "assistant", "function_call", "function_call_output"]
    assert payload["tools"][0] == {
        "type": "function",
        "name": "get_top_gainers",
        "description": "d",
        "strict": False,
        "parameters": {"type": "object", "properties": {}},
    }


def test_copilot_token_validation():
    from app.services.llm_provider import validate_copilot_token

    assert validate_copilot_token("")[0] is False
    assert validate_copilot_token("ghp_abc123")[0] is False
    assert "ghp_" in validate_copilot_token("ghp_abc123")[1]
    assert validate_copilot_token("gho_abc")[0] is True
    assert validate_copilot_token("ghu_abc")[0] is True
    assert validate_copilot_token("github_pat_abc")[0] is True
    assert validate_copilot_token("randomstring")[0] is False


def test_oauth_and_jwt_helpers():
    from app.services.codex_auth import (
        access_token_expiring_soon,
        chatgpt_account_id,
        decode_jwt_claims,
    )
    from app.services.llm_provider import _is_oauth_token

    assert _is_oauth_token("sk-ant-oat01-xyz") is True
    assert _is_oauth_token("sk-ant-api03-xyz") is False

    tok = _jwt(9999999999, "acct-123")
    assert decode_jwt_claims(tok)["https://api.openai.com/auth"]["chatgpt_account_id"] == "acct-123"
    assert chatgpt_account_id(tok) == "acct-123"
    assert access_token_expiring_soon(tok) is False
    assert access_token_expiring_soon("not-a-jwt") is True
    assert decode_jwt_claims("garbage") == {}


def test_provider_registry_allowlist_consistency():
    from app.routers.system_config import ALLOWED_STRING_KEYS
    from app.services.ai_config import ALL_PROVIDERS, PROVIDER_DB_KEYS

    missing = [k for k in PROVIDER_DB_KEYS.values() if k not in ALLOWED_STRING_KEYS]
    assert not missing
    assert "ai.codex_access_token" in ALLOWED_STRING_KEYS
    assert "ai.codex_refresh_token" in ALLOWED_STRING_KEYS
    for prov in (
        "anthropic",
        "claude-code",
        "openai",
        "openrouter",
        "deepseek",
        "xai",
        "together",
        "copilot",
        "codex",
    ):
        assert prov in ALL_PROVIDERS
