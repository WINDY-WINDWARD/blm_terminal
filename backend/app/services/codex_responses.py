"""OpenAI Responses API (Codex backend) format conversion + SSE parsing.

Simplified port of the Hermes Agent ``codex_responses_adapter.py``:
- Converts our internal OpenAI-style messages/tools to Responses ``input`` items.
- Parses the Codex SSE stream (``response.output_text.delta``,
  ``response.function_call_arguments.delta``, ``response.completed``/``failed``).
- Deliberately omits Hermes' encrypted-reasoning replay, native compaction, and
  preflight validation — plain history every turn (fewer tokens cached, zero risk
  of ``invalid_encrypted_content`` 400s after model switches).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Responses API caps call_id / function names (non-retryable 400 when exceeded).
_MAX_ITEM_ID_LENGTH = 64
_VALID_FN_NAME_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")


def _clamp_call_id(call_id: str) -> str:
    call_id = (call_id or "").strip()
    if len(call_id) <= _MAX_ITEM_ID_LENGTH:
        return call_id
    import hashlib

    return f"call_{hashlib.sha256(call_id.encode()).hexdigest()[:32]}"


def _sanitize_fn_name(name: str) -> str:
    if isinstance(name, str) and _VALID_FN_NAME_RE.fullmatch(name):
        return name
    coerced = re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_-]", "_", (name or "").strip())).strip("_")
    return (coerced[:64] or "fn")


def openai_tools_to_responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Convert chat-completions tool schemas to Responses function-tool schemas."""
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for item in tools:
        fn = item.get("function", {}) if isinstance(item, dict) else {}
        name = fn.get("name", "")
        if not name or not isinstance(name, str):
            continue
        converted.append(
            {
                "type": "function",
                "name": name.strip(),
                "description": fn.get("description", "") or "",
                "strict": False,
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted or None


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert internal OpenAI-style messages to Responses ``input`` items.

    - system → folded into ``instructions`` by the caller (dropped here).
    - user/assistant text → ``{"role", "content"}``.
    - assistant ``tool_calls`` → ``function_call`` items (call_id clamped).
    - tool → ``function_call_output`` items (call_id clamped).
    """
    items: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "system":
            continue
        if role == "tool":
            call_id = _clamp_call_id(str(msg.get("tool_call_id") or ""))
            if not call_id:
                continue
            content = msg.get("content", "")
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content if isinstance(content, str) else json.dumps(content),
                }
            )
            continue
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        text = content if isinstance(content, str) else (
            json.dumps(content) if content is not None else ""
        )
        if role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            if text.strip():
                items.append({"role": "assistant", "content": text})
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {}) if isinstance(tc.get("function"), dict) else {}
                name = fn.get("name", "")
                if not name:
                    continue
                args = fn.get("arguments", "{}") or "{}"
                items.append(
                    {
                        "type": "function_call",
                        "call_id": _clamp_call_id(str(tc.get("id") or tc.get("call_id") or "")),
                        "name": _sanitize_fn_name(name),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    }
                )
            if not text.strip() and not tool_calls:
                items.append({"role": "assistant", "content": " "})
        else:
            items.append({"role": "user", "content": text})
    return items


def build_responses_payload(
    *,
    model: str,
    instructions: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Build the POST body for ``{base}/responses``.

    NOTE: ``max_output_tokens`` is deliberately NOT sent. OpenAI dropped
    support for it on the ChatGPT-account Codex route (newer models such as
    gpt-5.5 reject it with ``400 Unsupported parameter``). Output length is
    bounded by ``reasoning.effort`` + the agentic-loop ``max_iter`` cap in
    the caller instead. ``max_tokens`` is accepted for signature
    compatibility but ignored.
    """
    _ = max_tokens
    payload: dict[str, Any] = {
        "model": model,
        "instructions": instructions or "You are a helpful assistant.",
        "input": chat_messages_to_responses_input(messages),
        "store": False,
        "stream": True,
        "reasoning": {"effort": "medium", "summary": "auto"},
    }
    response_tools = openai_tools_to_responses_tools(tools)
    if response_tools:
        payload["tools"] = response_tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = True
    return payload


class CodexStreamParser:
    """Incremental parser for the Codex Responses SSE stream.

    Emits our internal SSE event dicts: token / done / error. Tool calls are
    assembled from ``response.output_item.added`` skeletons +
    ``response.function_call_arguments.delta`` fragments, confirmed by the
    authoritative ``response.output_item.done`` /
    ``response.function_call_arguments.done`` frames (mirrors Hermes'
    _CodexResponseAssembler settlement).
    """

    def __init__(self) -> None:
        self.text = ""
        # output_index -> {"item_id": str, "call_id": str, "name": str, "arguments": str}
        self._pending: dict[int, dict[str, str]] = {}
        # item_id -> output_index (argument deltas may carry either correlator).
        self._by_item_id: dict[str, int] = {}
        # output_index -> finalized function_call item from .done frames.
        self._done_items: dict[int, dict[str, Any]] = {}
        self.saw_terminal = False
        self.status: str | None = None
        self.error_message: str | None = None

    def _entry_for_delta(self, ev: dict[str, Any]) -> dict[str, str]:
        """Resolve the pending call for an arguments-delta event."""
        item_id = str(ev.get("item_id") or "")
        if item_id and item_id in self._by_item_id:
            return self._pending[self._by_item_id[item_id]]
        idx = int(ev.get("output_index", 0))
        entry = self._pending.get(idx)
        if entry is None:
            entry = self._pending[idx] = {"item_id": item_id, "call_id": "", "name": "", "arguments": ""}
        if item_id and not entry["item_id"]:
            entry["item_id"] = item_id
            self._by_item_id[item_id] = idx
        return entry

    def feed(self, raw: str) -> list[dict[str, Any]]:
        """Feed one SSE ``data:`` payload. Returns internal events to forward."""
        out: list[dict[str, Any]] = []
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return out
        etype = ev.get("type", "")

        if etype == "response.output_text.delta":
            delta = ev.get("delta", "")
            if delta:
                self.text += delta
                out.append({"type": "token", "text": delta})
        elif etype == "response.refusal.delta":
            # The model declined on the refusal channel — still answer text
            # (a refusal-only stream must not end with zero content).
            delta = ev.get("delta", "")
            if isinstance(delta, str) and delta:
                self.text += delta
                out.append({"type": "token", "text": delta})
        elif etype == "response.output_item.added":
            item = ev.get("item", {}) or {}
            if item.get("type") == "function_call":
                idx = int(ev.get("output_index", len(self._pending)))
                item_id = str(item.get("id") or "")
                self._pending[idx] = {
                    "item_id": item_id,
                    "call_id": item.get("call_id") or item.get("id") or "",
                    "name": item.get("name") or "",
                    "arguments": str(item.get("arguments") or ""),
                }
                if item_id:
                    self._by_item_id[item_id] = idx
        elif etype == "response.function_call_arguments.delta":
            entry = self._entry_for_delta(ev)
            entry["arguments"] += ev.get("delta", "") or ""
        elif etype == "response.function_call_arguments.done":
            # Authoritative args snapshot (an explicit "" = zero-arg call).
            entry = self._entry_for_delta(ev)
            if ev.get("arguments") is not None:
                entry["arguments"] = str(ev["arguments"])
        elif etype == "response.output_item.done":
            item = ev.get("item", {}) or {}
            if item.get("type") == "function_call":
                idx = int(ev.get("output_index", -1))
                if idx < 0:
                    item_id = str(item.get("id") or "")
                    idx = self._by_item_id.get(item_id, len(self._done_items))
                self._done_items[idx] = item
                # Confirmed — drop the pending twin so it isn't settled twice.
                self._pending.pop(idx, None)
        elif etype in ("response.completed", "response.incomplete"):
            self.saw_terminal = True
            response = ev.get("response", {}) or {}
            self.status = response.get("status", "completed")
            if self.status == "incomplete":
                reason = ((response.get("incomplete_details") or {}).get("reason")) or "unknown"
                self.error_message = f"Response incomplete: {reason}"
        elif etype == "response.failed":
            self.saw_terminal = True
            response = ev.get("response", {}) or {}
            err = response.get("error") or {}
            self.status = "failed"
            self.error_message = err.get("message", "Response failed") if isinstance(err, dict) else str(err)
        elif etype == "error":
            self.saw_terminal = True
            self.status = "failed"
            err = ev.get("error") or ev.get("message", "Stream error")
            self.error_message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return out

    def tool_calls(self) -> list[dict[str, Any]]:
        """Finalize function calls: .done items win, pending calls settle in order."""
        merged: dict[int, dict[str, Any]] = {}
        for idx, entry in self._pending.items():
            if entry["name"]:
                merged[idx] = {
                    "id": entry["call_id"] or f"call_{idx}",
                    "type": "function",
                    "function": {
                        "name": entry["name"],
                        "arguments": (entry["arguments"] or "").strip() or "{}",
                    },
                }
        for idx, item in self._done_items.items():
            args = item.get("arguments")
            merged[idx] = {
                "id": item.get("call_id") or item.get("id") or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": args if isinstance(args, str) and args.strip() else "{}",
                },
            }
        result: list[dict[str, Any]] = []
        for idx in sorted(merged):
            if merged[idx]["function"]["name"]:
                result.append(merged[idx])
        return result
