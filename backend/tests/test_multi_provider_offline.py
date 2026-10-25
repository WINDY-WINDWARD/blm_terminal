import pytest
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


@pytest.mark.asyncio
async def test_proxy_loop_tool_call_turn():
    from app.services.llm_provider import _run_openai_loop
    from unittest.mock import MagicMock

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {"X-CPA-TRACE-ID": "test-trace-id-123"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aread(self):
            return b""

        async def aiter_lines(self):
            # 1. Output text delta
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "Let me check "}}]})
            yield "data: " + json.dumps({"choices": [{"delta": {"content": "that quote."}}]})
            # 2. Tool call delta
            yield "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_abc", "function": {"name": "get_symbol_data", "arguments": '{"sym'}}]}}]})
            yield "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'bol": "RELIANCE"}'}}]}}]})
            yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
            yield "data: [DONE]" 

    mock_client = MagicMock()
    mock_client.stream = lambda method, url, json=None, headers=None, **kwargs: MockStreamResponse()

    from unittest.mock import patch
    executed_tools = []
    async def fake_executor(tool_calls):
        executed_tools.extend(tool_calls)
        return ['{"type": "tool_result", "name": "get_symbol_data", "preview": "ok"}'], [{"role": "tool", "tool_call_id": "call_abc", "content": "{}"}]

    with patch("app.services.llm_provider._get_shared_client", return_value=mock_client):
        events = []
        async for chunk in _run_openai_loop(
            messages=[{"role": "user", "content": "quote"}],
            model="blm-prefix/gpt-4o",
            api_key="client-key",
            tools=[{"type": "function", "function": {"name": "get_symbol_data"}}],
            tool_executor=fake_executor,
            max_iter=1,  # Stop after tool execution in test
            base_url="http://127.0.0.1:8317/v1",
            retry_429=False,
        ):
            events.append(json.loads(chunk))

    assert any(e.get("type") == "token" and "Let me check" in e.get("text", "") for e in events)
    assert len(executed_tools) == 1
    assert executed_tools[0]["name"] == "get_symbol_data"
    assert executed_tools[0]["args"] == {"symbol": "RELIANCE"}


@pytest.mark.asyncio
async def test_proxy_loop_terminal_and_error():
    from app.services.llm_provider import _run_openai_loop
    from unittest.mock import MagicMock, patch

    class Mock429Stream:
        def __init__(self):
            self.status_code = 429
            self.headers = {"retry-after": "5"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aread(self):
            return b'{"error": "rate limited"}'

    mock_client = MagicMock()
    mock_client.stream = lambda *args, **kwargs: Mock429Stream()

    async def fake_executor(tool_calls):
        return [], []

    with patch("app.services.llm_provider._get_shared_client", return_value=mock_client):
        events = []
        async for chunk in _run_openai_loop(
            messages=[{"role": "user", "content": "hi"}],
            model="blm-prefix/gpt-4o",
            api_key="client-key",
            tools=[],
            tool_executor=fake_executor,
            max_iter=1,
            base_url="http://127.0.0.1:8123/v1",
            retry_429=False,
        ):
            events.append(json.loads(chunk))

        # Must immediately yield error without retrying 429 in BLM
        assert any(e.get("type") == "error" for e in events)


def test_proxy_request_conversion():
    from app.services.route_registry import (
        compute_oauth_proxy_prefix,
        format_route_model_id,
        parse_route_model_id,
    )

    prefix = compute_oauth_proxy_prefix("oauth:codex")
    assert prefix.startswith("blm-")

    pub_id = format_route_model_id("oauth:codex", "gpt-4o")
    assert pub_id == "blm:oauth:codex/gpt-4o"

    r_id, upstream = parse_route_model_id(pub_id)
    assert r_id == "oauth:codex"
    assert upstream == "gpt-4o"

    # Upstream with slashes
    slash_id = format_route_model_id("endpoint:xyz", "meta-llama/Llama-3-70b")
    r_id2, upstream2 = parse_route_model_id(slash_id)
    assert r_id2 == "endpoint:xyz"
    assert upstream2 == "meta-llama/Llama-3-70b"

    proxy_model = f"{prefix}/{upstream}"
    assert proxy_model == f"{prefix}/gpt-4o"


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

_QUOTA_BODY = """{ "error": { "code": 429, "message": "Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 19h56m16s.", "status": "RESOURCE_EXHAUSTED", "details": [ { "@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "QUOTA_EXHAUSTED" } ] } }"""


def test_gateway_quota_message_with_reset():
    from app.services.llm_provider import _friendly_gateway_error

    msg = _friendly_gateway_error("Antigravity API", 429, _QUOTA_BODY)
    assert "quota" in msg.lower()
    assert "19h56m16s" in msg
    assert "Settings" in msg
    assert "QUOTA_EXHAUSTED" not in msg


def test_gateway_quota_without_reset_window():
    from app.services.llm_provider import _friendly_gateway_error

    msg = _friendly_gateway_error("X", 429, "rate limit exceeded, slow down")
    assert "quota" in msg.lower()
    assert "{" not in msg


def test_gateway_auth_message():
    from app.services.llm_provider import _friendly_gateway_error

    msg = _friendly_gateway_error("Antigravity API", 401, "invalid token")
    assert "Settings" in msg
    assert "invalid token" not in msg


def test_gateway_generic_keeps_short_body():
    from app.services.llm_provider import _friendly_gateway_error

    msg = _friendly_gateway_error("Antigravity API", 503, "upstream exploded")
    assert msg.startswith("Antigravity API 503")
