"""LLM Provider module for abstracting AI API interactions."""

import json
import time
import logging
import asyncio
import os
import random
import re
import uuid
import httpx
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from urllib.parse import urlparse
from app.config import settings
from collections import deque
from datetime import datetime, timezone
from sqlalchemy import select
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.route_catalog import get_route_models
from app.services.route_registry import (
    compute_oauth_proxy_prefix,
    is_route_model_id,
    map_legacy_model_to_route,
    parse_route_model_id,
    resolve_active_route_id,
    ensure_model_belongs_to_route,
)

MAX_TRACE_ENTRIES = 100
_proxy_trace_ring: deque[dict[str, Any]] = deque(maxlen=MAX_TRACE_ENTRIES)


def record_proxy_trace(
    *,
    trace_id: str,
    route_id: str,
    session_id: str | None = None,
    status_code: int = 200,
    upstream_model: str | None = None,
    duration_ms: float | None = None,
) -> None:
    if not trace_id:
        return
    entry = {
        "trace_id": str(trace_id).strip(),
        "route_id": str(route_id).strip(),
        "session_id": str(session_id).strip() if session_id else "",
        "status_code": status_code,
        "upstream_model": str(upstream_model).strip() if upstream_model else "",
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _proxy_trace_ring.append(entry)


def get_proxy_traces(limit: int = 50) -> list[dict[str, Any]]:
    return list(_proxy_trace_ring)[-limit:]


def clear_proxy_traces() -> None:
    _proxy_trace_ring.clear()

from app.services.ai_config import get_dynamic_ai_provider, get_dynamic_ai_api_key

def _is_oauth_token(credential: str) -> bool:
    """True for Claude Code setup-tokens (sk-ant-oat…), which need Bearer auth."""
    return isinstance(credential, str) and credential.strip().startswith("sk-ant-oat")



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
    """Translate known gateway failure shapes into actionable messages without leaking raw bodies."""
    low = (body_text or "").lower()
    if "freetiererror" in low or "free tier can only be used from within opencode" in low:
        return (
            f"{api_label} free tier is unavailable right now — OpenCode is "
            "rate-limiting free requests from outside its own app. Wait a few "
            "minutes and retry, or switch to Zen Paid / another provider."
        )
    if "model is unavailable" in low:
        return (
            f"The selected model is currently unavailable on {api_label} "
            "(rotated or pulled). Pick another model."
        )
    if status_code == 500 and "internal server error" in low:
        return (
            f"{api_label} hit an internal error (likely free-tier capacity). "
            "Retry in a bit or switch provider."
        )
    # Quota exhaustion (Google RESOURCE_EXHAUSTED / QUOTA_EXHAUSTED, or
    # "Individual quota reached" style messages). Extract the reset window
    # ("Resets in 19h56m16s") when the provider includes one.
    if status_code == 429 or "resource_exhausted" in low or "quota" in low:
        reset = ""
        m = re.search(r"[Rr]esets? in ([0-9hms. ]+)", body_text or "")
        if m:
            reset = f" — resets in ~{m.group(1).strip()}"
        return (
            f"⏳ {api_label} daily quota reached{reset}. Upgrade the "
            "subscription for higher limits, or switch provider in "
            "Settings → AI."
        )
    if status_code in (401, 403):
        return (
            f"{api_label} rejected the credentials ({status_code}). "
            "Reconnect the provider in Settings → AI."
        )
    return f"{api_label} {status_code}: request failed."


def _friendly_network_error(api_label: str, exc: BaseException) -> str:
    """Name an httpx transport failure without leaking credentials or raw exception details."""
    kind = type(exc).__name__
    return (
        f"{api_label} network error ({kind}). "
        "The provider did not answer — retry, or pick another route."
    )

# Module-level shared httpx client and explicit stream deadlines
_SHARED_STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=330.0, write=60.0, pool=15.0)
_DEFAULT_STREAM_TIMEOUT = _SHARED_STREAM_TIMEOUT
_SHARED_CLIENT_TIMEOUT = _DEFAULT_STREAM_TIMEOUT

_FIRST_DELTA_DEADLINE = 240.0
_IDLE_DELTA_DEADLINE = 300.0
_TOTAL_STREAM_CAP = 600.0
# A wedged sidecar accepts the connection but never emits an event. Bound the
# wait for the first event so a stuck child is replaced instead of hanging the UI.
_PROXY_FIRST_EVENT_TIMEOUT = 150.0

# Agent-loop budget. Tool-driven turns can legitimately run long, so the cap is
# 60 turns with a one-shot instruction to wrap up at 45, and a wall-clock guard
# that ends the run cleanly before the transport budget aborts it mid-stream.
_DEFAULT_MAX_ITER = 60
_ITERATION_WARNING_AT = 45
_LOOP_WALL_CLOCK_CAP = 1500.0
_ITERATION_BUDGET_WARNING = (
    "You have 15 tool iterations remaining out of 60. "
    "Stop gathering new data, synthesise what you already have, and give your "
    "final answer now. If something essential is still missing, state that "
    "explicitly instead of continuing to call tools."
)
_WALL_CLOCK_EXHAUSTED_MESSAGE = (
    "Agent hit its 25-minute time budget before finishing. "
    "Narrow the question or retry."
)

_shared_clients: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


class StreamDeadlineTracker:
    def __init__(
        self,
        api_label: str,
        model: str,
        first_delta_deadline: float = _FIRST_DELTA_DEADLINE,
        idle_delta_deadline: float = _IDLE_DELTA_DEADLINE,
        total_stream_cap: float = _TOTAL_STREAM_CAP,
    ):
        self.api_label = api_label
        self.model = model
        self.first_delta_deadline = first_delta_deadline
        self.idle_delta_deadline = idle_delta_deadline
        self.total_stream_cap = total_stream_cap
        self.start_time = time.monotonic()
        self.last_meaningful_time = self.start_time
        self.has_meaningful_delta = False
        self.stage = "initial_response"

    def record_meaningful_delta(self):
        self.has_meaningful_delta = True
        self.last_meaningful_time = time.monotonic()
        self.stage = "streaming_deltas"

    def next_timeout(self) -> tuple[float, str]:
        now = time.monotonic()
        cap_remaining = (self.start_time + self.total_stream_cap) - now
        if cap_remaining <= 0:
            return 0.0, "TotalStreamTimeout"

        if not self.has_meaningful_delta:
            delta_remaining = (self.start_time + self.first_delta_deadline) - now
            timeout_type = "FirstDeltaTimeout"
        else:
            delta_remaining = (self.last_meaningful_time + self.idle_delta_deadline) - now
            timeout_type = "IdleDeltaTimeout"

        if delta_remaining <= 0:
            return 0.0, timeout_type

        if cap_remaining < delta_remaining:
            return cap_remaining, "TotalStreamTimeout"
        return delta_remaining, timeout_type

    def make_error_event(self, error_class: str, detail: str = "") -> dict[str, Any]:
        elapsed = time.monotonic() - self.start_time
        logger.error(
            "Stream timeout error: route=%s model=%s stage=%s elapsed=%.1fs error_class=%s",
            self.api_label,
            self.model,
            self.stage,
            elapsed,
            error_class,
        )
        msg = f"{self.api_label} timed out ({error_class}) during {self.stage}."
        if detail:
            msg = f"{msg} {detail}"
        else:
            msg = f"{msg} The provider did not respond in time."
        return {
            "type": "error",
            "error_class": error_class,
            "stage": self.stage,
            "message": msg,
        }


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_clients
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return httpx.AsyncClient(timeout=_DEFAULT_STREAM_TIMEOUT)
        
    if current_loop not in _shared_clients:
        _shared_clients[current_loop] = httpx.AsyncClient(timeout=_DEFAULT_STREAM_TIMEOUT)
    return _shared_clients[current_loop]

async def cleanup_shared_clients():
    """Properly close all shared HTTPX clients during app teardown to prevent connection leaks."""
    global _shared_clients
    for client in list(_shared_clients.values()):
        try:
            await client.aclose()
        except Exception as e:
            logger.warning("Error closing shared httpx client: %s", type(e).__name__)
    _shared_clients.clear()

def parse_sse_chunk(raw: str) -> dict[str, Any] | None:
    """Parse a single SSE data payload into a JSON object.

    Accepts raw payloads with or without the leading 'data:' prefix, stripped
    of line breaks. Returns None for '[DONE]', empty/blank lines, keep-alives,
    or malformed JSON (logging decode failures at DEBUG level without raising).
    """
    if not raw:
        return None
    s = raw.strip()
    if not s or s.startswith(":"):
        return None
    if s.startswith("data:"):
        s = s[5:].strip()
    if not s or s == "[DONE]":
        return None
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError as exc:
        logger.debug("Failed to decode SSE JSON chunk: %s", exc)
        return None


class StreamAccumulator:
    """Accumulates streaming deltas and tool-call fragments for one assistant turn."""

    def __init__(self) -> None:
        self.content: str = ""
        self.reasoning: str = ""
        self.finish_reason: str | None = None
        self.tool_calls_map: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] | None = None

    def apply(self, chunk: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a parsed SSE chunk to internal state.

        Returns an incremental event dict to emit (e.g. token or error), or None.
        Updates finish_reason, reasoning, content, and fragments in tool_calls_map.
        """
        if not isinstance(chunk, dict):
            return None

        if "usage" in chunk and chunk["usage"]:
            self.usage = chunk["usage"]

        choices = chunk.get("choices")
        if not choices:
            return None

        choice = choices[0]
        # Track finish_reason if present (do not overwrite with None)
        self.finish_reason = choice.get("finish_reason") or self.finish_reason
        delta = choice.get("delta") or {}

        if delta.get("reasoning_content"):
            self.reasoning += delta["reasoning_content"]

        content_delta = delta.get("content")
        if content_delta:
            self.content += content_delta

        for tc in delta.get("tool_calls", []):
            self._apply_tool_call(tc)

        if content_delta:
            return {"type": "token", "text": content_delta}
        return None

    def _apply_tool_call(self, tc: dict[str, Any]) -> None:
        idx = tc.get("index", 0)
        if idx not in self.tool_calls_map:
            self.tool_calls_map[idx] = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        entry = self.tool_calls_map[idx]
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
            idx = max(self.tool_calls_map) + 1
            self.tool_calls_map[idx] = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
            entry = self.tool_calls_map[idx]

        entry["id"] += frag_id
        fn = tc.get("function") or {}
        entry["function"]["name"] += fn.get("name") or ""
        entry["function"]["arguments"] += fn.get("arguments") or ""
        # Gemini 3.x ships a thought_signature alongside each
        # function call; it must be echoed back verbatim or
        # the next turn is rejected with a 400.
        if tc.get("extra_content") and not entry.get("extra_content"):
            entry["extra_content"] = tc["extra_content"]

    def has_meaningful_delta(self, chunk: dict[str, Any]) -> bool:
        """Return True if chunk contains content, reasoning, or tool calls."""
        choices = chunk.get("choices")
        if not choices:
            return False
        delta = choices[0].get("delta") or {}
        return bool(
            delta.get("reasoning_content")
            or delta.get("content")
            or delta.get("tool_calls")
        )

    def finalize(self) -> dict[str, Any]:
        """Return terminal summary of accumulated turn state."""
        return {
            "content": self.content,
            "reasoning": self.reasoning,
            "finish_reason": self.finish_reason,
            "tool_calls_map": self.tool_calls_map,
            "usage": self.usage,
        }


# The tool executor callback signature:
# Takes a list of normalized tool calls: [{"id": str, "name": str, "args": dict}]
# Returns: tuple(list[str] (sse_events), list[dict] (tool_messages for LLM history))
ToolExecutor = Callable[[list[dict[str, Any]]], Awaitable[tuple[list[str], list[dict[str, Any]]]]]


def _extract_normalised_tool_calls(
    tool_calls_map: dict[int, dict[str, Any]],
    passthrough_thought_signature: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Format tool calls for assistant message history, executor arguments, and SSE notifications.

    Returns:
        echoed_calls: tool calls array suitable for assistant message dict
        normalised: list of [{"id": ..., "name": ..., "args": ...}] for tool_executor
        events: list of JSON serialized tool_call SSE events
    """
    tool_calls_list = [tool_calls_map[i] for i in sorted(tool_calls_map)]
    echoed_calls: list[dict[str, Any]] = []
    normalised: list[dict[str, Any]] = []
    events: list[str] = []

    for tc in tool_calls_list:
        call = {"id": tc["id"], "type": "function", "function": tc["function"]}
        if passthrough_thought_signature and tc.get("extra_content"):
            call["extra_content"] = tc["extra_content"]
        echoed_calls.append(call)

        try:
            args_preview = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
        except json.JSONDecodeError:
            args_preview = {}
        events.append(json.dumps({"type": "tool_call", "name": tc["function"]["name"], "args": args_preview}))
        normalised.append({"id": tc["id"], "name": tc["function"]["name"], "args": args_preview})

    return echoed_calls, normalised, events


async def _read_sse_stream(
    line_iter: AsyncGenerator[str, None],
    tracker: StreamDeadlineTracker,
    accumulator: StreamAccumulator,
) -> AsyncGenerator[str, None]:
    """Iterate SSE lines, enforce deadline timeouts, and apply deltas to accumulator."""
    while True:
        timeout_val, timeout_type = tracker.next_timeout()
        if timeout_val <= 0:
            yield json.dumps(tracker.make_error_event(timeout_type))
            yield json.dumps({"type": "done"})
            return
        try:
            line = await asyncio.wait_for(line_iter.__anext__(), timeout=timeout_val)
        except StopAsyncIteration:
            break
        except (asyncio.TimeoutError, TimeoutError):
            yield json.dumps(tracker.make_error_event(timeout_type))
            yield json.dumps({"type": "done"})
            return

        chunk = parse_sse_chunk(line)
        if not chunk:
            continue

        token_event = accumulator.apply(chunk)
        if token_event:
            yield json.dumps(token_event)

        if accumulator.has_meaningful_delta(chunk):
            tracker.record_meaningful_delta()

        if accumulator.finish_reason:
            break


def _build_stream_error(
    exc: BaseException,
    tracker: StreamDeadlineTracker | None,
    api_label: str,
    model: str,
) -> tuple[str, str]:
    """Construct error class, log and return (error_event_json, done_event_json)."""
    error_class = type(exc).__name__
    stage = "initial_response" if (not tracker or not tracker.has_meaningful_delta) else "streaming_deltas"
    elapsed = (time.monotonic() - tracker.start_time) if tracker else 0.0
    if isinstance(exc, httpx.TimeoutException):
        logger.error("Stream timeout error: route=%s model=%s stage=%s elapsed=%.1fs error_class=%s", api_label, model, stage, elapsed, error_class)
        msg = f"{api_label} transport timed out ({error_class}) during {stage}."
    else:
        logger.error("Stream request error: route=%s model=%s stage=%s elapsed=%.1fs error_class=%s", api_label, model, stage, elapsed, error_class)
        msg = _friendly_network_error(api_label, exc)
    err = json.dumps({"type": "error", "error_class": error_class, "stage": stage, "message": msg})
    return err, json.dumps({"type": "done"})


def _format_stream_turn_headers(
    api_key: str,
    session_id: str | int | None,
    opencode_headers: bool,
    extra_headers: dict[str, str] | None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key or 'public'}",
        "Content-Type": "application/json",
    }
    if opencode_headers:
        headers.update(_opencode_headers(session_id))
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _build_turn_payload(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.6,
        "top_p": 0.95,
        "max_tokens": max_tokens if max_tokens is not None else 4096,
        "stream": True,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


async def _dispatch_stream_turn(
    client: httpx.AsyncClient,
    response: httpx.Response,
    tracker_config: tuple[float, float, float],
    api_label: str,
    model: str,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Consume the SSE stream from an open 200 response, yielding events and done summary."""
    init_first_dl, init_idle_dl, init_stream_cap = tracker_config
    tracker = StreamDeadlineTracker(
        api_label=api_label,
        model=model,
        first_delta_deadline=init_first_dl,
        idle_delta_deadline=init_idle_dl,
        total_stream_cap=init_stream_cap,
    )
    accumulator = StreamAccumulator()

    terminated = False
    async for ev in _read_sse_stream(response.aiter_lines(), tracker, accumulator):
        yield ("event", ev)
        # `_read_sse_stream` emits terminal events only for deadline
        # timeouts. Inspect the parsed type rather than substring-matching
        # the serialized JSON: assistant text may itself contain
        # '"type": "done"', which would suppress the turn summary and
        # leave the caller waiting for a done event that never arrives.
        if _is_terminal_stream_event(ev):
            terminated = True
    if not terminated:
        yield ("done", accumulator.finalize())


def _is_terminal_stream_event(event: str) -> bool:
    """Return True when a serialized stream event is a terminal error/done."""
    try:
        parsed = json.loads(event)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, dict) and parsed.get("type") in {"error", "done"}


async def _run_stream_turn(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    stream_kwargs: dict[str, Any],
    tracker_config: tuple[float, float, float],
    api_label: str,
    model: str,
    retry_429: bool,
    on_response_headers: Callable[[httpx.Headers, int], None] | None = None,
) -> AsyncGenerator[tuple[str, Any], None]:
    """Execute one streaming HTTP turn with retries, deadlines, and SSE parsing."""
    max_attempts = 4 if retry_429 else 1

    for attempt in range(max_attempts):
        tracker: StreamDeadlineTracker | None = None
        try:
            async with client.stream("POST", url, json=payload, headers=headers, **stream_kwargs) as response:
                if on_response_headers:
                    try:
                        on_response_headers(response.headers, response.status_code)
                    except Exception as trace_exc:
                        logger.debug("Trace callback exception: %s", type(trace_exc).__name__)

                if response.status_code == 429:
                    body = await response.aread()
                    if not retry_429:
                        msg = _friendly_gateway_error(api_label, response.status_code, body.decode(errors="replace"))
                        yield ("event", json.dumps({"type": "error", "message": msg}))
                        yield ("event", json.dumps({"type": "done"}))
                        return
                    wait_s = _rate_limit_wait(response.headers.get("retry-after"), body.decode(errors="replace"))
                    logger.warning("%s 429 (attempt %d/4) — waiting %.0fs", api_label, attempt + 1, wait_s)
                    await asyncio.sleep(wait_s)
                    continue

                if response.status_code != 200:
                    body = await response.aread()
                    msg = _friendly_gateway_error(api_label, response.status_code, body.decode(errors="replace"))
                    yield ("event", json.dumps({"type": "error", "message": msg}))
                    yield ("event", json.dumps({"type": "done"}))
                    return

                async for item in _dispatch_stream_turn(client, response, tracker_config, api_label, model):
                    yield item
                return
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            err_ev, done_ev = _build_stream_error(exc, tracker, api_label, model)
            yield ("event", err_ev)
            yield ("event", done_ev)
            return

    yield ("event", json.dumps({"type": "error", "message": f"{api_label} 429: rate limit persistent after retries"}))
    yield ("event", json.dumps({"type": "done"}))


async def _run_openai_loop(
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    max_iter: int = _DEFAULT_MAX_ITER,
    base_url: str | None = None,
    session_id: str | int | None = None,
    api_label: str = "Zen API",
    opencode_headers: bool = True,
    passthrough_thought_signature: bool = False,
    request_timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
    max_tokens: int | None = None,
    retry_429: bool = True,
    on_response_headers: Callable[[httpx.Headers, int], None] | None = None,
    first_byte_timeout: float | None = None,
    first_delta_deadline: float | None = None,
    idle_delta_deadline: float | None = None,
    total_stream_cap: float | None = None,
) -> AsyncGenerator[str, None]:
    if not base_url:
        raise RuntimeError("No base_url provided to _run_openai_loop")
    parsed = urlparse(base_url)
    if not _is_loopback_host(parsed.hostname):
        raise RuntimeError(f"base_url host must be loopback, got {parsed.hostname!r}")
    endpoint = base_url.rstrip("/")
    url = f"{endpoint}/chat/completions"
    headers = _format_stream_turn_headers(api_key, session_id, opencode_headers, extra_headers)
    stream_kwargs = {"timeout": request_timeout} if request_timeout is not None else {}
    tracker_config = (
        first_delta_deadline if first_delta_deadline is not None else (first_byte_timeout if first_byte_timeout is not None else _FIRST_DELTA_DEADLINE),
        idle_delta_deadline if idle_delta_deadline is not None else _IDLE_DELTA_DEADLINE,
        total_stream_cap if total_stream_cap is not None else _TOTAL_STREAM_CAP,
    )
    client = _get_shared_client()
    loop_started = time.monotonic()

    for _iteration in range(max_iter):
        if _iteration + 1 == _ITERATION_WARNING_AT:
            messages.append({"role": "system", "content": _ITERATION_BUDGET_WARNING})
            logger.info(
                "Agent loop reached %s of %s iterations; injected wrap-up warning",
                _iteration + 1,
                max_iter,
            )
        if time.monotonic() - loop_started > _LOOP_WALL_CLOCK_CAP:
            logger.warning(
                "Agent loop exceeded %.0fs wall clock after %s iterations",
                _LOOP_WALL_CLOCK_CAP,
                _iteration,
            )
            yield json.dumps({"type": "error", "message": _WALL_CLOCK_EXHAUSTED_MESSAGE})
            yield json.dumps({"type": "done"})
            return

        payload = _build_turn_payload(model, messages, tools, max_tokens)
        turn_gen = _run_stream_turn(
            client=client,
            url=url,
            payload=payload,
            headers=headers,
            stream_kwargs=stream_kwargs,
            tracker_config=tracker_config,
            api_label=api_label,
            model=model,
            retry_429=retry_429,
            on_response_headers=on_response_headers,
        )

        turn_summary = None
        async for kind, val in turn_gen:
            if kind == "event":
                yield val
            elif kind == "done":
                turn_summary = val

        if turn_summary is None:
            return

        echoed_calls, normalised, call_events = _extract_normalised_tool_calls(
            turn_summary["tool_calls_map"],
            passthrough_thought_signature=passthrough_thought_signature,
        )

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": turn_summary["content"] or None}
        if echoed_calls:
            assistant_msg["tool_calls"] = echoed_calls
        messages.append(assistant_msg)

        if normalised:
            for ev in call_events:
                yield ev
            sse_events, tool_msgs = await tool_executor(normalised)
            for ev in sse_events:
                yield ev
            for tm in tool_msgs:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tm.get("tool_call_id") or tm.get("id", ""),
                    "content": tm.get("content", ""),
                })
            continue

        yield json.dumps({"type": "done"})
        return

    yield json.dumps({"type": "error", "message": f"Agent reached the {max_iter}-iteration limit. Try a more specific question."})
    yield json.dumps({"type": "done"})


async def _stream_proxy_with_sync(supervisor, stream):
    try:
        async for chunk in stream:
            yield chunk
    finally:
        try:
            if hasattr(stream, "aclose"):
                await stream.aclose()
        except Exception:
            pass
        supervisor.request_sync()


async def _is_route_enabled(route_id: str) -> bool:
    try:
        from app.services.ai_config import is_ai_provider_configured

        if route_id.startswith("direct:"):
            return await is_ai_provider_configured(route_id)

        from app.database import AsyncSessionLocal
        from app.models.ai_provider import AIProviderRoute

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(AIProviderRoute.enabled).where(AIProviderRoute.id == route_id)
            )
            route_enabled = result.scalar_one_or_none() is True

        if not route_enabled:
            return False
        if route_id.startswith("oauth:"):
            return await is_ai_provider_configured(route_id)
        return True
    except Exception as exc:
        logger.warning("Failed to validate route %s (%s)", route_id, type(exc).__name__)
        return False




_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip("[]")
    return h in _LOOPBACK_HOSTS


def _loopback_proxy_base_url(host: str, port: int) -> str:
    """Build the sidecar base URL and refuse anything that is not loopback."""
    if not _is_loopback_host(host):
        raise RuntimeError("CLIProxyAPI must listen on loopback")
    return f"http://{host}:{port}/v1"


async def stream_chat_completion(
    messages: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    system_prompt: str | None = None,
    max_iter: int = _DEFAULT_MAX_ITER,
    session_id: str | int | None = None,
    max_tokens: int | None = None,
    allow_external_route: bool = False,
    first_delta_deadline: float | None = None,
    idle_delta_deadline: float | None = None,
) -> AsyncGenerator[str, None]:
    active_route_id = await resolve_active_route_id()
    qualified = model if is_route_model_id(model) else map_legacy_model_to_route(model, active_route_id)
    try:
        route_id, upstream_model = parse_route_model_id(qualified)
        if route_id != active_route_id:
            if not allow_external_route or not await _is_route_enabled(route_id):
                raise ValueError(f"Route '{route_id}' is disabled or unavailable for this request")
        ensure_model_belongs_to_route(qualified, route_id, await get_route_models(route_id))
    except (ValueError, RuntimeError) as exc:
        yield json.dumps({"type": "error", "message": "Selected model is unavailable for its provider route. Refresh the model list."})
        yield json.dumps({"type": "done"})
        return

    session_id_str = str(session_id).strip() if (session_id is not None and str(session_id).strip()) else f"blm-{uuid.uuid4().hex[:12]}"

    from app.services.direct_proxy_routes import direct_proxy_prefix, get_direct_route

    if route_id.startswith("direct:"):
        spec = get_direct_route(route_id)
        if spec is not None and not spec.supported:
            yield json.dumps({"type": "error", "message": spec.unavailable_reason})
            yield json.dumps({"type": "done"})
            return

    supervisor = get_proxy_supervisor()
    host, port, client_key = await supervisor.ensure_started()

    proxy_prefix = None
    if route_id.startswith(("oauth:", "endpoint:")):
        try:
            from app.database import AsyncSessionLocal
            from app.models.ai_provider import AIProviderRoute

            async with AsyncSessionLocal() as db_session:
                r_stmt = select(AIProviderRoute.proxy_prefix).where(AIProviderRoute.id == route_id)
                res = await db_session.execute(r_stmt)
                proxy_prefix = res.scalar_one_or_none()
        except Exception as exc:
            logger.debug("Failed to query route proxy_prefix from DB: %s", type(exc).__name__)

    if not proxy_prefix:
        if route_id.startswith("direct:"):
            proxy_prefix = direct_proxy_prefix(route_id)
        elif route_id.startswith("oauth:"):
            proxy_prefix = compute_oauth_proxy_prefix(route_id)
        else:
            proxy_prefix = route_id.replace(":", "-")

    proxy_model = f"{proxy_prefix}/{upstream_model}"

    def _capture_proxy_headers(hdrs: httpx.Headers, status_code: int) -> None:
        supervisor.request_sync()
        trace_id = hdrs.get("x-cpa-trace-id") or hdrs.get("X-CPA-TRACE-ID")
        if trace_id:
            record_proxy_trace(
                trace_id=trace_id,
                route_id=route_id,
                session_id=session_id_str,
                status_code=status_code,
                upstream_model=upstream_model,
            )

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    extra_headers = {"X-Session-Id": session_id_str}

    def _open_stream(h: str, p: int, ck: str):
        return _stream_proxy_with_sync(supervisor, _run_openai_loop(
            full_messages,
            proxy_model,
            ck,
            tools,
            tool_executor,
            max_iter=max_iter,
            base_url=_loopback_proxy_base_url(h, p),
            session_id=session_id_str,
            api_label=f"Proxy ({route_id})",
            opencode_headers=False,
            extra_headers=extra_headers,
            retry_429=False,
            on_response_headers=_capture_proxy_headers,
            max_tokens=max_tokens,
            first_delta_deadline=first_delta_deadline if first_delta_deadline is not None else _FIRST_DELTA_DEADLINE,
            idle_delta_deadline=idle_delta_deadline if idle_delta_deadline is not None else _IDLE_DELTA_DEADLINE,
            total_stream_cap=_TOTAL_STREAM_CAP,
        ))

    async def _first_event(stream):
        try:
            return await asyncio.wait_for(
                stream.__anext__(), timeout=_PROXY_FIRST_EVENT_TIMEOUT
            )
        except StopAsyncIteration:
            return None

    stream = _open_stream(host, port, client_key)
    try:
        first = None
        try:
            first = await _first_event(stream)
        except asyncio.TimeoutError:
            logger.warning(
                "Proxy produced no events within %.0fs; restarting sidecar",
                _PROXY_FIRST_EVENT_TIMEOUT,
            )
            try:
                if hasattr(stream, "aclose"):
                    await stream.aclose()
            except Exception:
                pass
            host, port, client_key = await supervisor.recover("first_event_timeout", preserve_oauth_flow=True)
            stream = _open_stream(host, port, client_key)
            first = await _first_event(stream)
        if first is not None:
            yield first
            async for chunk in stream:
                yield chunk
        else:
            yield json.dumps({"type": "done"})
    except Exception as exc:
        logger.warning("Proxy inference stream failed: %s", type(exc).__name__)
        yield json.dumps({"type": "error", "message": "Inference stream failed (connection error). Try again."})
        yield json.dumps({"type": "done"})
