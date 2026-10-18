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
        """Verify connectivity to the configured provider."""
        configured = await self.is_configured()
        self._provider_reachable = configured
        return configured

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

        if error_msg and not full_content.strip():
            logger.error("LLM completion returned error: %s", error_msg)
            raise RuntimeError(f"LLM API call failed: {error_msg}")

        return full_content.strip(), model

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
        summary, model = await self._generate_summary(
            messages=messages,
            system_prompt=ALERT_SUMMARIZER_SYSTEM_PROMPT,
            max_tokens=max_tokens,
        )

        cleaned_summary = " ".join(summary.split())

        return SummaryResult(
            summary=cleaned_summary,
            input_tokens=0,
            output_tokens=0,
            model=model,
        )

    async def close(self) -> None:
        """Close any persistent connections."""
        pass


ai_summarizer = AISummarizer()
