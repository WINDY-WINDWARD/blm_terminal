"""LLM Provider module for abstracting AI API interactions."""

import json
import logging
import asyncio
import os
import random
import re
import uuid
import httpx
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from app.config import settings
from app.services.antigravity_auth import get_antigravity_token
from app.services.ai_config import get_dynamic_ai_provider, get_dynamic_ai_api_key

# ---------------------------------------------------------------------------
# Claude Code identity for OAuth (subscription) requests.
# Anthropic routes OAuth by user-agent — requests without it intermittently
# 500 — and rejects UA versions too far behind the real release, so the
# installed `claude --version` is detected once per process with a static
# fallback kept current (mirrors Hermes' anthropic_adapter).
# ---------------------------------------------------------------------------
_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"
_claude_code_version_cache: str | None = None


def _get_claude_code_version() -> str:
    """Installed Claude Code version, else the static fallback (cached)."""
    global _claude_code_version_cache
    if _claude_code_version_cache is None:
        _claude_code_version_cache = _CLAUDE_CODE_VERSION_FALLBACK
        try:
            import subprocess

            for cmd in ("claude", "claude-code"):
                try:
                    result = subprocess.run(
                        [cmd, "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        version = result.stdout.strip().split()[0]
                        if version and version[0].isdigit():
                            _claude_code_version_cache = version
                            break
                except Exception:
                    continue
        except Exception:
            pass
    return _claude_code_version_cache


# Beta gates for OAuth/subscription auth (matches Claude Code / pi-ai / OpenCode).
# oauth-2025-04-20 enables Bearer auth (without it: 401 "OAuth authentication
# is currently not supported"); claude-code-20250219 is the Claude Code gate.
_OAUTH_BETAS = (
    "interleaved-thinking-2025-05-14,"
    "fine-grained-tool-streaming-2025-05-14,"
    "claude-code-20250219,oauth-2025-04-20"
)

# System prefix Hermes injects for OAuth (Anthropic validates the client
# identity; without it the credential can 400 as "only authorized for use
# with Claude Code").
_CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."


def _is_oauth_token(credential: str) -> bool:
    """True for Claude Code setup-tokens (sk-ant-oat…), which need Bearer auth."""
    return isinstance(credential, str) and credential.strip().startswith("sk-ant-oat")


# ---------------------------------------------------------------------------
# GitHub Copilot inference-token cache.
# A raw GitHub token is NOT usable for inference directly — it must be
# exchanged at https://api.github.com/copilot_internal/v2/token for a
# short-lived `tid=…` token (~30 min TTL). Cached here with the server's
# expires_at; refreshed 2 min early (mirrors Hermes' copilot_auth).
# ---------------------------------------------------------------------------
_copilot_token: str | None = None
_copilot_token_expires_at: float = 0.0
_copilot_token_base_url: str | None = None
_copilot_token_fp: str | None = None

_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_DEFAULT_BASE_URL = "https://api.githubcopilot.com"
_COPILOT_EXCHANGE_USER_AGENT = "GitHubCopilotChat/0.26.7"
_COPILOT_EDITOR_VERSION = "vscode/1.104.1"
_COPILOT_EDITOR_HEADERS = {
    "Editor-Version": _COPILOT_EDITOR_VERSION,
    "User-Agent": _COPILOT_EXCHANGE_USER_AGENT,
    "Copilot-Integration-Id": "vscode-chat",
    "Openai-Intent": "conversation-panel",
    "X-Initiator": "agent",
}

# Token families the Copilot API exchanges (mirrors Hermes' validate_copilot_token).
# Classic PATs (ghp_*) are rejected upstream with an opaque error — fail fast here.
_COPILOT_SUPPORTED_PREFIXES = ("gho_", "github_pat_", "ghu_")
_COPILOT_EXCHANGE_ATTEMPTS = 3
_COPILOT_REFRESH_MARGIN_SECONDS = 120


def validate_copilot_token(token: str) -> tuple[bool, str]:
    """Check the token family before any network call. Returns (ok, message)."""
    token = (token or "").strip()
    if not token or token == "none":
        return False, "No GitHub token configured"
    if token.startswith("ghp_"):
        return (
            False,
            "Classic Personal Access Tokens (ghp_*) are not accepted by the Copilot API. "
            "Use a fine-grained PAT (github_pat_*) with Copilot access, "
            "`gh auth login` (gho_*), or the Copilot CLI / extension OAuth token (ghu_*).",
        )
    if not token.startswith(_COPILOT_SUPPORTED_PREFIXES):
        return (
            False,
            f"Unsupported GitHub token format for the Copilot API. "
            f"Supported prefixes: {', '.join(_COPILOT_SUPPORTED_PREFIXES)}.",
        )
    return True, "OK"


def _try_gh_cli_token() -> str | None:
    """`gh auth token` fallback when no usable env/DB token is set (cached 5 min)."""
    import shutil
    import subprocess

    gh = shutil.which("gh")
    if not gh:
        return None
    try:
        result = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True, text=True, timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def _derive_copilot_base_url(api_token: str, endpoints: Any) -> str:
    """Account-specific inference host: exchange `endpoints.api` wins (enterprise /
    proxied accounts), else derive from the token's `proxy-ep`, else default."""
    if isinstance(endpoints, dict):
        api_ep = str(endpoints.get("api") or "").strip().rstrip("/")
        if api_ep:
            return api_ep
    m = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", api_token or "")
    if m:
        host = re.sub(r"^https?://", "", m.group(1), count=1).rstrip("/")
        host = re.sub(r"^proxy\.", "api.", host, count=1)
        if host:
            return f"https://{host}"
    return _COPILOT_DEFAULT_BASE_URL


async def get_copilot_inference_token(
    gh_token: str,
) -> tuple[str | None, str, str | None]:
    """Exchange a GitHub token for (inference_token, base_url, error).

    Returns (None, base_url, error_message) when the exchange fails — the
    error message is user-actionable (bad token family vs network vs denied).
    """
    global _copilot_token, _copilot_token_expires_at, _copilot_token_base_url, _copilot_token_fp

    import hashlib
    import time as _time

    token = (gh_token or "").strip()
    if (not token or token == "none") and not os.environ.get("COPILOT_GITHUB_TOKEN"):
        # `gh auth token` fallback only when no explicit token is configured,
        # so an exported-but-invalid token is never silently overridden.
        cli_token = await asyncio.to_thread(_try_gh_cli_token)
        if cli_token:
            token = cli_token

    fp = hashlib.sha256(token.encode()).hexdigest()[:16] if token else None
    now = _time.time()
    if (
        _copilot_token
        and fp == _copilot_token_fp
        and _copilot_token_expires_at > (now + _COPILOT_REFRESH_MARGIN_SECONDS)
    ):
        return _copilot_token, _copilot_token_base_url or _COPILOT_DEFAULT_BASE_URL, None

    valid, msg = validate_copilot_token(token)
    if not valid:
        return None, _COPILOT_DEFAULT_BASE_URL, msg

    last_exc: Exception | None = None
    for attempt in range(1, _COPILOT_EXCHANGE_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    _COPILOT_TOKEN_URL,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"token {token}",
                        "User-Agent": _COPILOT_EXCHANGE_USER_AGENT,
                        "Editor-Version": _COPILOT_EDITOR_VERSION,
                    },
                )
            if resp.status_code in (401, 403, 404):
                return None, _COPILOT_DEFAULT_BASE_URL, (
                    f"GitHub rejected the token (HTTP {resp.status_code}). "
                    "Check that it has Copilot access and is not expired."
                )
            if resp.status_code != 200:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                await asyncio.sleep(1.5 * attempt)
                continue
            data = resp.json()
            api_token = data.get("token", "")
            if not api_token:
                return None, _COPILOT_DEFAULT_BASE_URL, "Copilot exchange returned an empty token."
            try:
                expires_at = float(data.get("expires_at") or 0) or (now + 1800)
            except (TypeError, ValueError):
                expires_at = now + 1800
            base_url = _derive_copilot_base_url(api_token, data.get("endpoints"))
            _copilot_token = api_token
            _copilot_token_expires_at = expires_at
            _copilot_token_base_url = base_url
            _copilot_token_fp = fp
            return _copilot_token, base_url, None
        except Exception as e:
            last_exc = e
            if attempt < _COPILOT_EXCHANGE_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)
    return None, _COPILOT_DEFAULT_BASE_URL, f"Copilot token exchange failed: {last_exc}"


def clear_copilot_token_cache() -> None:
    """Drop the cached inference token (e.g. after the GH token is rotated)."""
    global _copilot_token, _copilot_token_expires_at, _copilot_token_base_url, _copilot_token_fp
    _copilot_token = None
    _copilot_token_expires_at = 0.0
    _copilot_token_base_url = None
    _copilot_token_fp = None


# Back-compat alias: the previous constant name pointed at the default host.
_COPILOT_BASE_URL = _COPILOT_DEFAULT_BASE_URL

# ---------------------------------------------------------------------------
# OpenCode client identity — mirrors packages/opencode/src/session/llm/request.ts
# The Zen gateway expects these headers so requests are treated as originating
# from within OpenCode (required for the free tier).
# ---------------------------------------------------------------------------
_OPENCODE_VERSION = "1.18.31"
_OPENCODE_CLIENT = "cli"


def _opencode_headers(session_id: str | int | None = None) -> dict[str, str]:
    """Build the OpenCode identity headers for a Zen API request.

    x-opencode-session is stable per chat session (aids prompt caching);
    x-opencode-request is fresh per LLM call.
    """
    sid = f"ses_{session_id}" if session_id is not None else f"ses_{uuid.uuid4().hex[:24]}"
    return {
        "User-Agent": f"opencode/{_OPENCODE_VERSION}",
        "x-opencode-client": _OPENCODE_CLIENT,
        "x-opencode-session": sid,
        "x-opencode-request": f"msg_{uuid.uuid4().hex[:24]}",
    }

import weakref

logger = logging.getLogger(__name__)


def _rate_limit_wait(retry_after: str | None, body: str = "") -> float:
    """Parse how long to wait before retrying a 429 response (seconds)."""
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 180.0)
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)s", body)
    if m:
        try:
            return min(max(float(m.group(1)) + 5.0, 1.0), 180.0)
        except ValueError:
            pass
    return 60.0


def _friendly_gateway_error(api_label: str, status_code: int, body_text: str) -> str:
    """Translate known gateway failure shapes into actionable messages.

    The Zen free tier in particular fails in cryptic ways (FreeTierError
    rate-limiting, rotated models, capacity 500s). Users get guidance
    instead of a raw JSON blob; the raw excerpt is kept for debugging.
    """
    raw = body_text[:200]
    low = body_text.lower()
    if "freetiererror" in low or "free tier can only be used from within opencode" in low:
        return (
            f"{api_label} free tier is unavailable right now — OpenCode is "
            "rate-limiting free requests from outside its own app. Wait a few "
            "minutes and retry, or switch to Zen Paid / another provider. "
            f"(Raw: {raw})"
        )
    if "model is unavailable" in low:
        return (
            f"The selected model is currently unavailable on {api_label} "
            f"(rotated or pulled). Pick another model. (Raw: {raw})"
        )
    if status_code == 500 and "internal server error" in low:
        return (
            f"{api_label} hit an internal error (likely free-tier capacity). "
            f"Retry in a bit or switch provider. (Raw: {raw})"
        )
    return f"{api_label} {status_code}: {body_text[:300]}"

# Mirrors the plugin's getRandomizedHeaders() from constants.js
_AG_VERSION = "2.5.5"
_AG_PLATFORMS = ["windows/amd64", "darwin/arm64", "darwin/amd64"]
_AG_API_CLIENTS = [
    "google-cloud-sdk antigravity/2.5.5"
]

def _get_antigravity_headers(token: str) -> dict[str, str]:
    platform = random.choice(_AG_PLATFORMS)
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": f"antigravity/{_AG_VERSION} {platform}",
        "X-Goog-Api-Client": random.choice(_AG_API_CLIENTS),
        "Content-Type": "application/json",
    }

# ---------------------------------------------------------------------------
# Gemini schema transformer — port of toGeminiSchema() from gemini.js
# Antigravity uses strict protobuf validation:
#   - type values must be UPPERCASE ("object" → "OBJECT")
#   - several JSON-Schema fields are unsupported and must be stripped
#   - ARRAY types must have an 'items' field
# ---------------------------------------------------------------------------
_UNSUPPORTED_SCHEMA_FIELDS = frozenset({
    "additionalProperties", "$schema", "$id", "$comment", "$ref", "$defs",
    "definitions", "const", "contentMediaType", "contentEncoding",
    "if", "then", "else", "not", "patternProperties",
    "unevaluatedProperties", "unevaluatedItems",
    "dependentRequired", "dependentSchemas", "propertyNames",
    "minContains", "maxContains",
})

def _to_gemini_schema(schema: Any) -> Any:
    """Recursively transform a JSON Schema dict to Gemini-compatible format."""
    if not schema or not isinstance(schema, dict):
        return schema
    property_names: set[str] = set(schema.get("properties", {}).keys())
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_SCHEMA_FIELDS:
            continue
        if key == "type" and isinstance(value, str):
            result[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            result[key] = {k: _to_gemini_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = _to_gemini_schema(value)
        elif key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
            result[key] = [_to_gemini_schema(i) for i in value]
        elif key == "required" and isinstance(value, list):
            if property_names:
                valid = [p for p in value if isinstance(p, str) and p in property_names]
                if valid:
                    result[key] = valid
            else:
                result[key] = value
        else:
            result[key] = value
    # Gemini requires ARRAY schemas to have an 'items' field
    if result.get("type") == "ARRAY" and "items" not in result:
        result["items"] = {"type": "STRING"}
    return result


# Module-level shared httpx client
_SHARED_CLIENT_TIMEOUT = 120.0
_shared_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

def _get_shared_client() -> httpx.AsyncClient:
    global _shared_clients
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # Fallback if no loop is running yet (shouldn't really happen during async execution)
        return httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT)
        
    if current_loop not in _shared_clients:
        _shared_clients[current_loop] = httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT)
    return _shared_clients[current_loop]

async def cleanup_shared_clients():
    """Properly close all shared HTTPX clients during app teardown to prevent connection leaks."""
    global _shared_clients
    for client in list(_shared_clients.values()):
        try:
            await client.aclose()
        except Exception as e:
            logger.warning(f"Error closing shared httpx client: {e}")
    _shared_clients.clear()

MAX_ITER = 10
ANTHROPIC_MODELS: frozenset[str] = frozenset({"minimax-m2.5", "minimax-m2.7"})

# The tool executor callback signature:
# Takes a list of normalized tool calls: [{"id": str, "name": str, "args": dict}]
# Returns: tuple(list[str] (sse_events), list[dict] (tool_messages for LLM history))
ToolExecutor = Callable[[list[dict[str, Any]]], Awaitable[tuple[list[str], list[dict[str, Any]]]]]


async def _run_openai_loop(
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    max_iter: int = 10,
    base_url: str | None = None,
    session_id: str | int | None = None,
    api_label: str = "Zen API",
    opencode_headers: bool = True,
    passthrough_thought_signature: bool = False,
    request_timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    endpoint = base_url or settings.zen_base_url
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key or 'public'}",
        "Content-Type": "application/json",
    }
    if opencode_headers:
        headers.update(_opencode_headers(session_id))
    if extra_headers:
        headers.update(extra_headers)
    
    client = _get_shared_client()
    for _iteration in range(max_iter):
        payload = {
            "model": model,
            "temperature": 0.6,
            "top_p": 0.95,
            "max_tokens": 4096,
            "stream": True,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Resilient streaming request: on 429, wait out the rate limit and
        # re-issue the same payload (no state lost — we are at the top of an
        # iteration). Bounded so a hard outage still surfaces as an error.
        # NOTE: some OpenAI-compatible gateways (Google AI Studio) return
        # finish_reason "stop" even when tool_calls are present, so tool
        # execution takes priority over the finish reason below.
        streamed: tuple[str, str, str | None, dict[int, dict[str, Any]]] | None = None
        stream_kwargs: dict[str, Any] = {}
        if request_timeout is not None:
            stream_kwargs["timeout"] = request_timeout
        for _attempt in range(4):
            try:
                async with client.stream("POST", url, json=payload, headers=headers, **stream_kwargs) as response:
                    if response.status_code == 429:
                        body = await response.aread()
                        wait_s = _rate_limit_wait(
                            response.headers.get("retry-after"), body.decode(errors="replace")
                        )
                        logger.warning("%s 429 (attempt %d/4) — waiting %.0fs", api_label, _attempt + 1, wait_s)
                        await asyncio.sleep(wait_s)
                        continue
                    if response.status_code != 200:
                        body = await response.aread()
                        msg = _friendly_gateway_error(api_label, response.status_code, body.decode(errors="replace"))
                        yield json.dumps({"type": "error", "message": msg})
                        yield json.dumps({"type": "done"})
                        return

                    content = ""
                    reasoning = ""
                    finish_reason: str | None = None
                    tool_calls_map: dict[int, dict[str, Any]] = {}

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices")
                        if not choices:
                            continue
                        choice = choices[0]
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta", {})

                        if delta.get("reasoning_content"):
                            reasoning += delta["reasoning_content"]

                        if delta.get("content"):
                            content += delta["content"]
                            yield json.dumps({"type": "token", "text": delta["content"]})

                        for tc in delta.get("tool_calls", []):
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                            entry = tool_calls_map[idx]
                            frag_id = tc.get("id") or ""
                            # Some OpenAI-compatible gateways (Google AI Studio)
                            # omit `index` on parallel tool calls — every
                            # fragment defaults to 0. A new non-empty id on an
                            # already-started entry means a new call: allocate
                            # a fresh slot instead of concatenating garbage.
                            if (
                                frag_id
                                and entry["id"]
                                and frag_id != entry["id"]
                                and entry["function"]["name"]
                            ):
                                idx = max(tool_calls_map) + 1
                                tool_calls_map[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                entry = tool_calls_map[idx]
                            entry["id"] += frag_id
                            fn = tc.get("function") or {}
                            entry["function"]["name"] += fn.get("name") or ""
                            entry["function"]["arguments"] += fn.get("arguments") or ""
                            # Gemini 3.x ships a thought_signature alongside each
                            # function call; it must be echoed back verbatim or
                            # the next turn is rejected with a 400.
                            if tc.get("extra_content") and not entry.get("extra_content"):
                                entry["extra_content"] = tc["extra_content"]
                    streamed = (content, reasoning, finish_reason, tool_calls_map)
                    break
            except httpx.RequestError as exc:
                yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
                yield json.dumps({"type": "done"})
                return

        if streamed is None:
            yield json.dumps({"type": "error", "message": f"{api_label} 429: rate limit persistent after retries"})
            yield json.dumps({"type": "done"})
            return
        content, reasoning, finish_reason, tool_calls_map = streamed

        tool_calls_list = [tool_calls_map[i] for i in sorted(tool_calls_map)]

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls_list:
            echoed_calls = []
            for tc in tool_calls_list:
                call = {"id": tc["id"], "type": "function", "function": tc["function"]}
                if passthrough_thought_signature and tc.get("extra_content"):
                    call["extra_content"] = tc["extra_content"]
                echoed_calls.append(call)
            assistant_msg["tool_calls"] = echoed_calls
        messages.append(assistant_msg)

        if tool_calls_list:
            normalised = []
            for tc in tool_calls_list:
                try:
                    args_preview = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                except json.JSONDecodeError:
                    args_preview = {}
                yield json.dumps({"type": "tool_call", "name": tc["function"]["name"], "args": args_preview})
                normalised.append({"id": tc["id"], "name": tc["function"]["name"], "args": args_preview})

            sse_events, tool_msgs = await tool_executor(normalised)

            for ev in sse_events:
                yield ev

            for tm in tool_msgs:
                messages.append({"role": "tool", "tool_call_id": tm["id"], "content": tm["content"]})
            continue

        yield json.dumps({"type": "done"})
        return

    yield json.dumps({"type": "error", "message": f"Agent exceeded {max_iter} iterations. Try a more specific question."})
    yield json.dumps({"type": "done"})


async def _run_anthropic_loop(
    messages: list[dict[str, Any]],
    system_prompt: str,
    model: str,
    api_key: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    max_iter: int = 10,
    base_url: str | None = None,
    session_id: str | int | None = None,
    auth_mode: str = "api_key",
    opencode_headers: bool = True,
) -> AsyncGenerator[str, None]:
    endpoint = base_url or settings.zen_base_url
    url = f"{endpoint}/messages"
    if auth_mode == "oauth":
        # Claude Code setup-token (sk-ant-oat01…): Bearer auth behind the OAuth
        # beta gate + Claude Code client identity (mirrors Hermes'
        # build_anthropic_client style="oauth"). Without oauth-2025-04-20 the
        # API 401s ("OAuth authentication is currently not supported");
        # without the claude-code user-agent it intermittently 500s or 400s
        # ("only authorized for use with Claude Code").
        headers = {
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": _OAUTH_BETAS,
            "Content-Type": "application/json",
            "user-agent": f"claude-code/{_get_claude_code_version()} (external, cli)",
            "x-app": "cli",
        }
    else:
        headers = {
            "x-api-key": api_key or "public",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if opencode_headers:
            headers.update(_opencode_headers(session_id))
    client = _get_shared_client()
    
    for _iteration in range(max_iter):
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "stream": True,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    msg = _friendly_gateway_error("Zen API", response.status_code, body.decode(errors="replace"))
                    yield json.dumps({"type": "error", "message": msg})
                    yield json.dumps({"type": "done"})
                    return

                block_types: dict[int, str] = {}
                block_ids: dict[int, str] = {}
                block_names: dict[int, str] = {}
                block_args: dict[int, str] = {}
                block_text: dict[int, str] = {}
                stop_reason: str | None = None

                async for line in response.aiter_lines():
                    if not line.startswith("data:"): continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]": continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError: continue

                    etype = ev.get("type", "")

                    if etype == "content_block_start":
                        idx = ev["index"]
                        block = ev.get("content_block", {})
                        btype = block.get("type", "")
                        block_types[idx] = btype
                        if btype == "tool_use":
                            block_ids[idx] = block.get("id", "")
                            block_names[idx] = block.get("name", "")
                            block_args[idx] = ""
                        elif btype == "text":
                            block_text[idx] = ""

                    elif etype == "content_block_delta":
                        idx = ev["index"]
                        delta = ev.get("delta", {})
                        dtype = delta.get("type", "")

                        if dtype == "text_delta":
                            text = delta.get("text", "")
                            block_text[idx] = block_text.get(idx, "") + text
                            yield json.dumps({"type": "token", "text": text})
                        elif dtype == "input_json_delta":
                            block_args[idx] = block_args.get(idx, "") + delta.get("partial_json", "")

                    elif etype == "message_delta":
                        stop_reason = ev.get("delta", {}).get("stop_reason")

        except httpx.RequestError as exc:
            yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
            yield json.dumps({"type": "done"})
            return

        content_blocks: list[dict[str, Any]] = []
        tool_use_indices: list[int] = []

        for idx in sorted(block_types):
            btype = block_types[idx]
            if btype == "text":
                text_val = block_text.get(idx, "")
                if text_val:
                    content_blocks.append({"type": "text", "text": text_val})
            elif btype == "tool_use":
                try:
                    input_val = json.loads(block_args.get(idx, "{}") or "{}")
                except json.JSONDecodeError:
                    input_val = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": block_ids[idx],
                    "name": block_names[idx],
                    "input": input_val,
                })
                tool_use_indices.append(idx)

        messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason == "end_turn" or (stop_reason is None and not tool_use_indices):
            yield json.dumps({"type": "done"})
            return

        if tool_use_indices:
            normalised = []
            for idx in tool_use_indices:
                try:
                    args_preview = json.loads(block_args.get(idx, "{}") or "{}")
                except json.JSONDecodeError:
                    args_preview = {}
                yield json.dumps({"type": "tool_call", "name": block_names[idx], "args": args_preview})
                normalised.append({"id": block_ids[idx], "name": block_names[idx], "args": args_preview})

            sse_events, tool_msgs = await tool_executor(normalised)

            for ev in sse_events:
                yield ev

            tool_result_blocks = [
                {"type": "tool_result", "tool_use_id": tm["id"], "content": tm["content"]}
                for tm in tool_msgs
            ]
            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        yield json.dumps({"type": "done"})
        return

    yield json.dumps({"type": "error", "message": f"Agent exceeded {max_iter} iterations."})
    yield json.dumps({"type": "done"})


async def _run_antigravity_loop(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    max_iter: int = 10,
) -> AsyncGenerator[str, None]:
    token = await get_antigravity_token()
    if not token:
        yield json.dumps({"type": "error", "message": "Failed to get Antigravity token. Please authenticate."})
        yield json.dumps({"type": "done"})
        return

    _TIERS = ("-low", "-medium", "-high")
    if not any(model.endswith(t) for t in _TIERS):
        if "flash" in model:
            model += "-low"
        elif "pro" in model:
            model += "-low"
        
    url = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"
    headers = _get_antigravity_headers(token)

    gemini_tools = [{"functionDeclarations": []}]
    if tools:
        for t in tools:
            fn = t.get("function", t)
            decl = {
                "name": fn["name"],
                "description": fn["description"],
                "parameters": _to_gemini_schema(fn.get("parameters", {}))
            }
            gemini_tools[0]["functionDeclarations"].append(decl)

    client = _get_shared_client()
    empty_retries = 0
    
    for _iteration in range(max_iter):
        contents = []
        system_text: str | None = None
        for m in messages:
            role = m["role"]
            if role == "system":
                # Accumulate system text; emitted as systemInstruction, not a content turn
                system_text = (system_text + "\n\n" + m["content"]) if system_text else m["content"]
            elif role == "user":
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"].append({"text": m["content"]})
                else:
                    contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            elif role == "assistant":
                parts = []
                if m.get("content"):
                    parts.append({"text": m["content"]})
                if m.get("tool_calls"):
                    first_fc = True
                    for tc in m["tool_calls"]:
                        args_str = tc["function"].get("arguments", "{}")
                        if not args_str:
                            args_str = "{}"
                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            args = {}
                        fc_part: dict[str, Any] = {
                            "functionCall": {
                                "name": tc["function"]["name"],
                                "args": args
                            }
                        }
                        if first_fc:
                            # First functionCall in a model turn MUST carry a
                            # thought_signature. Use the captured value if present,
                            # otherwise inject the sentinel to avoid a 400 error.
                            sig = tc.get("thought_signature") or "skip_thought_signature_validator"
                            fc_part["thought_signature"] = sig
                            fc_part["thoughtSignature"] = sig
                            first_fc = False
                        # Parallel calls (index > 0) must NOT carry a signature.
                        parts.append(fc_part)
                contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                part = {
                    "functionResponse": {
                        "name": m.get("name", "unknown_tool"),
                        "response": {"result": m.get("content", "")}
                    }
                }
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})

        request_body: dict[str, Any] = {
            "sessionId": "terminal-session",
            "contents": contents,
            "generationConfig": {
                "thinkingConfig": {
                    "includeThoughts": True,
                    "thinkingLevel": "high" if model.endswith("-high") else ("low" if model.endswith("-low") else "medium")
                }
            }
        }
        if system_text:
            # Mirror plugin: systemInstruction.role = "user", parts[0].text
            request_body["systemInstruction"] = {
                "role": "user",
                "parts": [{"text": system_text}]
            }
        if gemini_tools[0]["functionDeclarations"]:
            request_body["tools"] = gemini_tools

        # Fix model name for PRO models (API rejects -high/-medium suffix in the model string itself)
        # We must send -low in the model string, but keep thinkingLevel=high in generationConfig
        wire_model = model
        if "pro" in wire_model:
            for t in _TIERS:
                if wire_model.endswith(t):
                    wire_model = wire_model[:-len(t)] + "-low"
                    break

        payload = {
            "project": "rising-fact-p41fc",
            "model": wire_model,
            "requestType": "agent",
            "userAgent": "antigravity",
            "requestId": "agent-random-uuid",
            "request": request_body,
        }

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.error("Antigravity API error %s: %s", response.status_code, body.decode()[:500])
                    yield json.dumps({"type": "error", "message": f"Antigravity API {response.status_code}: {body.decode()[:300]}"})
                    yield json.dumps({"type": "done"})
                    return

                content = ""
                tool_calls_list = []
                
                async for line in response.aiter_lines():
                    if not line.startswith("data:"): continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]": continue
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError: continue

                    response_wrapper = chunk.get("response", chunk)
                    candidates = response_wrapper.get("candidates", [])
                    if not candidates: continue
                    parts = (candidates[0].get("content") or {}).get("parts", [])
                    
                    for part in parts:
                        if "text" in part:
                            delta = part["text"]
                            content += delta
                            yield json.dumps({"type": "token", "text": delta})
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            # Capture the thought_signature emitted alongside this
                            # functionCall part — the API requires it on the first
                            # functionCall in the next turn's model content block.
                            sig = part.get("thoughtSignature") or part.get("thought_signature")
                            tool_calls_list.append({
                                "id": f"call_{len(tool_calls_list)}",
                                "type": "function",
                                "thought_signature": sig,
                                "function": {
                                    "name": fc["name"],
                                    "arguments": json.dumps(fc.get("args", {}))
                                }
                            })

        except httpx.RequestError as exc:
            yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
            yield json.dumps({"type": "done"})
            return

        if not content and not tool_calls_list:
            empty_retries += 1
            if empty_retries > 1:
                yield json.dumps({"type": "error", "message": "Model returned empty response after retry."})
                yield json.dumps({"type": "done"})
                return
            continue

        empty_retries = 0
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls_list:
            assistant_msg["tool_calls"] = tool_calls_list
        messages.append(assistant_msg)

        if not tool_calls_list:
            yield json.dumps({"type": "done"})
            return

        normalised = []
        for tc in tool_calls_list:
            try:
                args_preview = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            except json.JSONDecodeError:
                args_preview = {}
            yield json.dumps({"type": "tool_call", "name": tc["function"]["name"], "args": args_preview})
            normalised.append({"id": tc["id"], "name": tc["function"]["name"], "args": args_preview})

        sse_events, tool_msgs = await tool_executor(normalised)

        for ev in sse_events:
            yield ev

        for tm in tool_msgs:
            tname = "unknown_tool"
            for n in normalised:
                if n["id"] == tm["id"]:
                    tname = n["name"]
                    break
            messages.append({"role": "tool", "tool_call_id": tm["id"], "name": tname, "content": tm["content"]})
        continue

    yield json.dumps({"type": "error", "message": f"Agent exceeded {max_iter} iterations."})
    yield json.dumps({"type": "done"})


async def _run_codex_loop(
    messages: list[dict[str, Any]],
    instructions: str,
    model: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    max_iter: int = 10,
    base_url: str | None = None,
    session_id: str | int | None = None,
) -> AsyncGenerator[str, None]:
    """Agentic loop over the OpenAI Responses API (ChatGPT Codex backend).

    Message history is kept in OpenAI chat shape and converted to Responses
    ``input`` items on every turn via codex_responses helpers.
    """
    from app.services.codex_auth import (
        CODEX_BASE_URL,
        CODEX_ORIGINATOR,
        CODEX_USER_AGENT,
        chatgpt_account_id,
        get_codex_access_token,
    )
    from app.services.codex_responses import CodexStreamParser, build_responses_payload

    access_token = await get_codex_access_token()
    if not access_token:
        yield json.dumps({"type": "error", "message": "Codex is not signed in. Sign in via Settings → AI → Codex."})
        yield json.dumps({"type": "done"})
        return

    endpoint = (base_url or CODEX_BASE_URL).rstrip("/")
    url = f"{endpoint}/responses"

    def _headers(token: str) -> dict[str, str]:
        # Identity headers mirror Hermes' codex_cloudflare_headers: third-party
        # harnesses must identify themselves; ChatGPT-Account-Id comes from the
        # OAuth JWT (required for some account shapes).
        h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": CODEX_USER_AGENT,
            "originator": CODEX_ORIGINATOR,
        }
        acct = chatgpt_account_id(token)
        if acct:
            h["ChatGPT-Account-Id"] = acct
        if session_id is not None:
            # Transcript identity + cache-routing hint (mirrors Hermes'
            # session_id / x-client-request-id extra headers).
            h["session_id"] = str(session_id)
            h["x-client-request-id"] = f"pck_{uuid.uuid4().hex[:24]}"
        return h

    headers = _headers(access_token)
    client = _get_shared_client()

    for _iteration in range(max_iter):
        payload = build_responses_payload(
            model=model,
            instructions=instructions,
            messages=messages,
            tools=tools,
        )
        parser = CodexStreamParser()
        refreshed_once = False

        while True:  # single retry on 401 with a forced token refresh
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code == 401 and not refreshed_once:
                        new_token = await get_codex_access_token(force_refresh=True)
                        if new_token:
                            headers = _headers(new_token)
                            refreshed_once = True
                            continue
                        yield json.dumps({"type": "error", "message": "Codex session expired. Sign in again via Settings → AI → Codex."})
                        yield json.dumps({"type": "done"})
                        return
                    if response.status_code == 429:
                        yield json.dumps({"type": "error", "message": "Codex quota exhausted (429). Credentials are still valid — retry after the usage limit resets."})
                        yield json.dumps({"type": "done"})
                        return
                    if response.status_code != 200:
                        body = await response.aread()
                        raw = body.decode(errors="replace")[:300]
                        lowered = raw.lower()
                        if response.status_code == 400 and "not supported" in lowered:
                            # Model retired or gated by ChatGPT plan (the Codex
                            # backend exposes no /models catalog, so availability
                            # varies by account/rollout).
                            msg = (
                                f"Codex: model '{model}' isn't available on your ChatGPT plan "
                                f"(or is retired). Pick another model in Settings → AI "
                                f"(gpt-5.6-terra works on all plans). Details: {raw}"
                            )
                        elif response.status_code == 400 and "unsupported parameter" in lowered:
                            msg = (
                                f"Codex rejected a request parameter for model '{model}'. "
                                f"Please report this (include the model name). Details: {raw}"
                            )
                        else:
                            msg = f"Codex API {response.status_code}: {raw}"
                        yield json.dumps({"type": "error", "message": msg})
                        yield json.dumps({"type": "done"})
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        for ev in parser.feed(raw):
                            if ev.get("type") == "token":
                                yield json.dumps(ev)
                    break
            except httpx.RequestError as exc:
                yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
                yield json.dumps({"type": "done"})
                return

        if parser.status == "failed":
            yield json.dumps({"type": "error", "message": f"Codex error: {(parser.error_message or 'unknown')[:300]}"})
            yield json.dumps({"type": "done"})
            return
        if parser.status == "incomplete":
            yield json.dumps({"type": "error", "message": f"Codex incomplete response: {(parser.error_message or '')[:200]}"})
            yield json.dumps({"type": "done"})
            return

        tool_calls_list = parser.tool_calls()
        if not parser.saw_terminal and not parser.text.strip() and not tool_calls_list:
            # Mirrors Hermes: no terminal frame AND no usable content means the
            # stream was truncated or rejected — never silently end the turn.
            yield json.dumps({"type": "error", "message": "Codex stream did not emit a terminal response."})
            yield json.dumps({"type": "done"})
            return

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": parser.text or None}
        if tool_calls_list:
            assistant_msg["tool_calls"] = [
                {"id": tc["id"], "type": "function", "function": tc["function"]}
                for tc in tool_calls_list
            ]
        messages.append(assistant_msg)

        if not tool_calls_list:
            yield json.dumps({"type": "done"})
            return

        normalised = []
        for tc in tool_calls_list:
            try:
                args_preview = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            except json.JSONDecodeError:
                args_preview = {}
            yield json.dumps({"type": "tool_call", "name": tc["function"]["name"], "args": args_preview})
            normalised.append({"id": tc["id"], "name": tc["function"]["name"], "args": args_preview})

        sse_events, tool_msgs = await tool_executor(normalised)
        for ev in sse_events:
            yield ev
        for tm in tool_msgs:
            messages.append({"role": "tool", "tool_call_id": tm["id"], "content": tm["content"]})

    yield json.dumps({"type": "error", "message": f"Agent exceeded {max_iter} iterations."})
    yield json.dumps({"type": "done"})


async def stream_chat_completion(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    system_prompt: str | None = None,
    max_iter: int = 10,
    session_id: str | int | None = None,
) -> AsyncGenerator[str, None]:
    provider = await get_dynamic_ai_provider()
    if provider == "gemini":
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        async for chunk in _run_antigravity_loop(full_messages, model, tools, tool_executor, max_iter):
            yield chunk
        return

    if provider == "codex":
        # ChatGPT subscription via the Responses API (OAuth, no API key).
        full_messages = [m for m in messages if m.get("role") != "system"]
        async for chunk in _run_codex_loop(
            full_messages, system_prompt or "", model, tools, tool_executor, max_iter,
            session_id=session_id,
        ):
            yield chunk
        return

    api_key = await get_dynamic_ai_api_key(provider)

    # zen-free needs no key ("public" is accepted by the gateway); every other
    # Zen-family provider requires one.
    if provider == "zen-free":
        api_key = "public"
    elif not api_key or api_key == "none":
        yield json.dumps({"type": "error", "message": f"{provider.upper()} API Key is not configured."})
        yield json.dumps({"type": "done"})
        return

    # Native Anthropic endpoints: direct API key or Claude Code OAuth token.
    # An oat token pasted into the plain `anthropic` slot is auto-detected by
    # prefix (mirrors Hermes' _is_oauth_token routing).
    if provider in ("anthropic", "claude-code"):
        oauth_mode = provider == "claude-code" or _is_oauth_token(api_key)
        sys_prompt = system_prompt or ""
        if oauth_mode and not sys_prompt.startswith(_CLAUDE_CODE_SYSTEM_PREFIX):
            # OAuth clients are expected to identify as Claude Code (Hermes'
            # _apply_claude_code_identity). Prepend only — never rewrite.
            sys_prompt = f"{_CLAUDE_CODE_SYSTEM_PREFIX} {sys_prompt}".strip()
        anthropic_messages = [m for m in messages if m.get("role") != "system"]
        async for chunk in _run_anthropic_loop(
            anthropic_messages,
            sys_prompt,
            model,
            api_key,
            tools,
            tool_executor,
            max_iter,
            base_url="https://api.anthropic.com/v1",
            session_id=session_id,
            auth_mode="oauth" if oauth_mode else "api_key",
            opencode_headers=False,
        ):
            yield chunk
        return

    # GitHub Copilot: exchange the GH token for a short-lived inference token.
    if provider == "copilot":
        copilot_token, copilot_base_url, copilot_error = await get_copilot_inference_token(api_key)
        if not copilot_token:
            yield json.dumps({"type": "error", "message": f"Copilot not available. {copilot_error or 'Check the GitHub token.'}"})
            yield json.dumps({"type": "done"})
            return
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        async for chunk in _run_openai_loop(
            full_messages, model, copilot_token, tools, tool_executor, max_iter,
            base_url=copilot_base_url, session_id=session_id,
            api_label="Copilot", opencode_headers=False,
            extra_headers=_COPILOT_EDITOR_HEADERS,
        ):
            yield chunk
        return

    # Third-party OpenAI-compatible endpoints (AI Studio, Groq) get plain
    # Bearer auth with no OpenCode identity headers. AI Studio additionally
    # needs Gemini thought_signatures echoed back in tool calls.
    api_label = "Zen API"
    use_opencode_headers = True
    passthrough_thought_signature = False
    request_timeout: float | None = None
    extra_headers: dict[str, str] | None = None
    if provider in ("zen-free", "zen-paid", "zen"):
        base_url = "https://opencode.ai/zen/v1"
    elif provider == "go":
        base_url = "https://opencode.ai/zen/go/v1"
    elif provider == "aistudio":
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        api_label = "AI Studio"
        use_opencode_headers = False
        passthrough_thought_signature = True
    elif provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        api_label = "Groq"
        use_opencode_headers = False
    elif provider == "nvidia":
        base_url = "https://integrate.api.nvidia.com/v1"
        api_label = "NVIDIA"
        use_opencode_headers = False
        # NIM serverless cold starts can exceed 2 minutes on large models.
        request_timeout = 300.0
    elif provider == "openai":
        base_url = "https://api.openai.com/v1"
        api_label = "OpenAI"
        use_opencode_headers = False
    elif provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        api_label = "OpenRouter"
        use_opencode_headers = False
        extra_headers = {
            "HTTP-Referer": "https://localhost:4455",
            "X-Title": "BLM Terminal",
        }
    elif provider == "deepseek":
        base_url = "https://api.deepseek.com/v1"
        api_label = "DeepSeek"
        use_opencode_headers = False
    elif provider == "xai":
        base_url = "https://api.x.ai/v1"
        api_label = "xAI"
        use_opencode_headers = False
    elif provider == "together":
        base_url = "https://api.together.xyz/v1"
        api_label = "Together"
        use_opencode_headers = False
    else:
        base_url = settings.zen_base_url

    # The Anthropic wire protocol only applies to these models on the Zen
    # gateway — on any other provider (e.g. minimax models via NVIDIA NIM)
    # they use the standard OpenAI loop.
    if model in ANTHROPIC_MODELS and provider in ("zen-free", "zen-paid", "zen", "go"):
        anthropic_messages = [m for m in messages if m.get("role") != "system"]
        sys_prompt = system_prompt or ""
        async for chunk in _run_anthropic_loop(anthropic_messages, sys_prompt, model, api_key, tools, tool_executor, max_iter, base_url=base_url, session_id=session_id):
            yield chunk
    else:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        async for chunk in _run_openai_loop(full_messages, model, api_key, tools, tool_executor, max_iter, base_url=base_url, session_id=session_id, api_label=api_label, opencode_headers=use_opencode_headers, passthrough_thought_signature=passthrough_thought_signature, request_timeout=request_timeout, extra_headers=extra_headers):
            yield chunk
