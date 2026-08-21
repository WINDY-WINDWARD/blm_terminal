"""LLM Provider module for abstracting AI API interactions."""

import json
import logging
import asyncio
import random
import httpx
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from app.config import settings
from app.services.antigravity_auth import get_antigravity_token

import weakref

logger = logging.getLogger(__name__)

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
) -> AsyncGenerator[str, None]:
    url = f"{settings.zen_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
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

        try:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    yield json.dumps({"type": "error", "message": f"Zen API {response.status_code}: {body.decode()[:300]}"})
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
                        entry["id"] += tc.get("id") or ""
                        fn = tc.get("function") or {}
                        entry["function"]["name"] += fn.get("name") or ""
                        entry["function"]["arguments"] += fn.get("arguments") or ""

        except httpx.RequestError as exc:
            yield json.dumps({"type": "error", "message": f"Network error: {exc}"})
            yield json.dumps({"type": "done"})
            return

        tool_calls_list = [tool_calls_map[i] for i in sorted(tool_calls_map)]

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls_list:
            assistant_msg["tool_calls"] = tool_calls_list
        messages.append(assistant_msg)

        if finish_reason == "stop" or (finish_reason is None and not tool_calls_list):
            yield json.dumps({"type": "done"})
            return

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
) -> AsyncGenerator[str, None]:
    url = f"{settings.zen_base_url}/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
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
                    yield json.dumps({"type": "error", "message": f"Zen API {response.status_code}: {body.decode()[:300]}"})
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


async def stream_chat_completion(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    system_prompt: str | None = None,
    max_iter: int = 10,
) -> AsyncGenerator[str, None]:
    if settings.ai_provider == "antigravity":
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        async for chunk in _run_antigravity_loop(full_messages, model, tools, tool_executor, max_iter):
            yield chunk
        return

    api_key = settings.opencode_zen_api_key
    if not api_key or api_key == "none":
        yield json.dumps({"type": "error", "message": "OPENCODE_ZEN_API_KEY is not configured."})
        yield json.dumps({"type": "done"})
        return

    if model in ANTHROPIC_MODELS:
        anthropic_messages = [m for m in messages if m.get("role") != "system"]
        sys_prompt = system_prompt or ""
        async for chunk in _run_anthropic_loop(anthropic_messages, sys_prompt, model, api_key, tools, tool_executor, max_iter):
            yield chunk
    else:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        async for chunk in _run_openai_loop(full_messages, model, api_key, tools, tool_executor, max_iter):
            yield chunk
