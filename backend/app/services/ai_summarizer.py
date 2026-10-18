"""AI Summarizer service backed by the multi-provider LLM pipeline."""

import json
import logging
from typing import Any

from app.schemas.ai_summarizer import SummaryResult
from app.services.ai_config import is_ai_provider_configured, get_configured_verifier_model
from app.services.llm_provider import stream_chat_completion
from app.services.prompts import (
    ALERT_SUMMARIZER_SYSTEM_PROMPT,
    FINANCIAL_SUMMARIZER_SYSTEM_PROMPT,
)

logger = logging.getLogger("app.services.ai_summarizer")
logger.setLevel(logging.DEBUG)

_MAX_INPUT_CHARS = 24000


class AISummarizer:
    """Financial statement and alerts summarizer backed by the configured multi-provider LLM."""

    def __init__(self) -> None:
        self._provider_reachable: bool | None = None

    async def is_configured(self) -> bool:
        """Return True if the active AI provider is properly configured."""
        return await is_ai_provider_configured()

    async def ping_provider(self) -> bool:
        """Verify live connectivity and auth to the configured provider via a 1-token probe."""
        if not await self.is_configured():
            self._provider_reachable = False
            return False

        try:
            model = await get_configured_verifier_model()

            async def _noop_executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
                return [], []

            got_token_or_done = False
            async for chunk in stream_chat_completion(
                messages=[{"role": "user", "content": "ping"}],
                model=model,
                tools=[],
                tool_executor=_noop_executor,
                system_prompt="ping",
                max_iter=1,
                max_tokens=1,
            ):
                try:
                    evt = json.loads(chunk)
                except json.JSONDecodeError:
                    continue

                if evt.get("type") == "error":
                    logger.warning("AI provider ping returned error: %s", evt.get("message"))
                    self._provider_reachable = False
                    return False

                if evt.get("type") in ("token", "done"):
                    got_token_or_done = True

            self._provider_reachable = got_token_or_done
            return got_token_or_done
        except Exception as exc:
            logger.warning("AI provider ping failed: %s", exc)
            self._provider_reachable = False
            return False

    async def _generate_summary(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        max_tokens: int = 512,
    ) -> tuple[str, str, int, int]:
        """Execute text generation through stream_chat_completion using the configured verifier model."""
        model = await get_configured_verifier_model()

        async def _noop_executor(tool_calls: list[dict]) -> tuple[list[str], list[dict]]:
            return [], []

        full_content = ""
        error_msg = None
        input_tokens = 0
        output_tokens = 0

        try:
            async for chunk in stream_chat_completion(
                messages=messages,
                model=model,
                tools=[],
                tool_executor=_noop_executor,
                system_prompt=system_prompt,
                max_iter=5,
                max_tokens=max_tokens,
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
                elif evt_type == "usage":
                    input_tokens = evt.get("input_tokens", input_tokens)
                    output_tokens = evt.get("output_tokens", output_tokens)
        except Exception as exc:
            logger.error("LLM completion call failed: %s", exc)
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        if error_msg:
            logger.error("LLM completion returned error: %s", error_msg)
            raise RuntimeError(f"LLM API call failed: {error_msg}")

        summary = full_content.strip()
        if not summary:
            raise RuntimeError("LLM returned an empty summary")

        if not input_tokens:
            input_tokens = max(1, sum(len(str(m.get("content", ""))) for m in messages) // 4)
        if not output_tokens:
            output_tokens = max(1, len(summary) // 4)

        return summary, model, input_tokens, output_tokens

    async def summarize(self, text: str, max_tokens: int = 512) -> SummaryResult:
        """Send text to the configured verifier model and return a structured financial summary."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if len(text) > _MAX_INPUT_CHARS:
            raise ValueError(f"Input text too long (max {_MAX_INPUT_CHARS} characters)")

        messages = [{"role": "user", "content": text}]
        summary, model, in_tok, out_tok = await self._generate_summary(
            messages=messages,
            system_prompt=FINANCIAL_SUMMARIZER_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )

        return SummaryResult(
            summary=summary,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=model,
        )

    async def summarize_alerts(
        self,
        symbol: str,
        alerts: list[dict],
        max_tokens: int = 350,
    ) -> SummaryResult:
        """Send formatted alerts to the configured verifier model and return a single cohesive paragraph summary."""
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
        summary, model, in_tok, out_tok = await self._generate_summary(
            messages=messages,
            system_prompt=ALERT_SUMMARIZER_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )

        cleaned_summary = " ".join(summary.split())

        return SummaryResult(
            summary=cleaned_summary,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=model,
        )

    async def close(self) -> None:
        """Close any persistent connections."""
        pass


ai_summarizer = AISummarizer()
