"""AI Summarizer service backed by the multi-provider LLM pipeline."""

import asyncio
import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.schemas.ai_summarizer import AlertDigestResult, SummaryResult
from app.services.ai_config import is_ai_provider_configured, get_configured_verifier_model
from app.services.llm_provider import stream_chat_completion
from app.services.prompts import (
    ALERT_SUMMARIZER_SYSTEM_PROMPT,
    FINANCIAL_SUMMARIZER_SYSTEM_PROMPT,
)

logger = logging.getLogger("app.services.ai_summarizer")
logger.setLevel(logging.DEBUG)

_MAX_INPUT_CHARS = 24000
_PING_TIMEOUT_SECONDS = 20.0
_DIGEST_FIELD_HINTS = frozenset({"bias", "summary", "trigger", "invalidation", "risk"})


def _parse_digest_object(candidate: str) -> dict[str, Any] | None:
    """Parse a plain, tagged, or fenced JSON object candidate."""
    candidate = candidate.strip()
    if not candidate:
        return None

    fence = re.fullmatch(r"```(?:json|text)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _iter_json_objects(content: str):
    """Yield top-level JSON objects embedded in prose, from left to right."""
    decoder = json.JSONDecoder()
    position = 0
    while True:
        start = content.find("{", position)
        if start == -1:
            return
        try:
            payload, end = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(payload, dict):
            yield payload
        position = start + end


def _extract_digest_payload(content: str) -> dict[str, Any]:
    """Extract the final valid digest object from tagged, fenced, or prose output."""
    candidates = list(re.finditer(
        r"<digest>\s*(.*?)\s*</digest>",
        content,
        re.DOTALL | re.IGNORECASE,
    ))
    for match in reversed(candidates):
        payload = _parse_digest_object(match.group(1))
        if payload is not None and _DIGEST_FIELD_HINTS.intersection(payload):
            return payload

    fences = list(re.finditer(
        r"```(?:json|text)?\s*(.*?)\s*```",
        content,
        re.DOTALL | re.IGNORECASE,
    ))
    for match in reversed(fences):
        payload = _parse_digest_object(match.group(1))
        if payload is not None and _DIGEST_FIELD_HINTS.intersection(payload):
            return payload

    fallback: dict[str, Any] | None = None
    for payload in _iter_json_objects(content):
        if _DIGEST_FIELD_HINTS.intersection(payload):
            fallback = payload
    if fallback is not None:
        return fallback

    raise RuntimeError("LLM returned an invalid alert digest")


class AISummarizer:
    """Financial statement and alerts summarizer backed by the configured multi-provider LLM."""

    def __init__(self) -> None:
        self._provider_reachable: bool | None = None

    async def is_configured(self) -> bool:
        """Return True if the active AI provider is properly configured."""
        return await is_ai_provider_configured()

    async def ping_provider(self) -> bool:
        """Verify live connectivity and auth using a bounded token probe."""
        if not await self.is_configured():
            self._provider_reachable = False
            return False

        try:
            model = await get_configured_verifier_model()

            async def _noop_executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
                return [], []

            async def _probe() -> bool:
                async for chunk in stream_chat_completion(
                    messages=[{"role": "user", "content": "Reply with exactly OK."}],
                    model=model,
                    tools=[],
                    tool_executor=_noop_executor,
                    system_prompt="Return one short acknowledgement.",
                    max_iter=1,
                    max_tokens=32,
                    allow_external_route=True,
                ):
                    try:
                        evt = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue

                    if evt.get("type") == "error":
                        logger.warning("AI provider ping returned error: %s", evt.get("message"))
                        return False
                    if evt.get("type") == "token":
                        return True

                return False

            self._provider_reachable = await asyncio.wait_for(
                _probe(), timeout=_PING_TIMEOUT_SECONDS
            )
            return self._provider_reachable
        except TimeoutError:
            logger.warning("AI provider ping timed out after %.0fs", _PING_TIMEOUT_SECONDS)
            self._provider_reachable = False
            return False
        except Exception as exc:
            logger.warning("AI provider ping failed: %s", exc)
            self._provider_reachable = False
            return False

    async def _generate_summary(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        max_tokens: int = 512,
    ) -> tuple[str, str]:
        """Execute text generation through stream_chat_completion using the configured verifier model."""
        model = await get_configured_verifier_model()

        async def _noop_executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
            return [], []

        full_content = ""
        error_msg = None

        try:
            async for chunk in stream_chat_completion(
                messages=messages,
                model=model,
                tools=[],
                tool_executor=_noop_executor,
                system_prompt=system_prompt,
                max_iter=5,
                max_tokens=max_tokens,
                allow_external_route=True,
            ):
                try:
                    evt = json.loads(chunk)
                except json.JSONDecodeError:
                    continue

                evt_type = evt.get("type")
                if evt_type == "token":
                    full_content += evt.get("text", "")
                elif evt_type == "error":
                    error_msg = evt.get("message", "LLM inference error")
        except Exception as exc:
            logger.error("LLM completion call failed: %s", exc)
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        if error_msg:
            logger.error("LLM completion returned error: %s", error_msg)
            raise RuntimeError(f"LLM API call failed: {error_msg}")

        summary = full_content.strip()
        if not summary:
            raise RuntimeError("LLM returned an empty summary")

        return summary, model

    async def summarize(self, text: str, max_tokens: int = 512) -> SummaryResult:
        """Send text to the configured verifier model and return a structured financial summary."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if len(text) > _MAX_INPUT_CHARS:
            raise ValueError(f"Input text too long (max {_MAX_INPUT_CHARS} characters)")

        messages = [{"role": "user", "content": text}]
        summary, model = await self._generate_summary(
            messages=messages,
            system_prompt=FINANCIAL_SUMMARIZER_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )

        return SummaryResult(
            summary=summary,
            input_tokens=0,
            output_tokens=0,
            model=model,
        )

    async def summarize_alerts(
        self,
        symbol: str,
        alerts: list[dict],
        max_tokens: int = 2048,
    ) -> AlertDigestResult:
        """Send formatted alerts to the configured verifier model and return a structured digest."""
        if not symbol or not symbol.strip():
            raise ValueError("Symbol cannot be empty")
        if not alerts:
            raise ValueError("Alerts list cannot be empty")

        formatted_lines = [f"Stock Symbol: {symbol.strip().upper()}"]
        for idx, a in enumerate(alerts, 1):
            t_type = str(a.get("trigger_type") or "ALERT").replace("_", " ").upper()
            time_str = str(a.get("triggered_at") or a.get("triggered_date") or "").strip()
            msg = str(a.get("message") or "").strip()
            formatted_lines.append(f"{idx}. [{t_type}] ({time_str}): {msg}")

        user_content = "\n".join(formatted_lines)
        if len(user_content) > _MAX_INPUT_CHARS:
            raise ValueError(f"Input text too long (max {_MAX_INPUT_CHARS} characters)")

        messages = [{"role": "user", "content": user_content}]
        raw_digest, model = await self._generate_summary(
            messages=messages,
            system_prompt=ALERT_SUMMARIZER_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )

        payload = _extract_digest_payload(raw_digest)
        try:
            return AlertDigestResult.model_validate({
                **payload,
                "input_tokens": 0,
                "output_tokens": 0,
                "model": model,
            })
        except ValidationError as exc:
            logger.error("LLM returned an invalid alert digest: %s", exc)
            raise RuntimeError("LLM returned an invalid alert digest") from exc

    async def close(self) -> None:
        """Close any persistent connections."""
        pass


ai_summarizer = AISummarizer()
