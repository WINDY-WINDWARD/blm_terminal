"""AI Summarizer service using an OpenAI-compatible Chat Completions API."""

import logging

from openai import AsyncOpenAI, APIConnectionError, AuthenticationError, OpenAIError

from app.config import settings
from app.schemas.ai_summarizer import SummaryResult
from app.services.prompts import FINANCIAL_SUMMARIZER_SYSTEM_PROMPT

logger = logging.getLogger("app.services.ai_summarizer")
logger.setLevel(logging.DEBUG)

_MAX_INPUT_CHARS = 24000


async def _get_api_key() -> str:
    """Fetch AI API key from settings or fallback to dynamic system_config."""
    api_key = settings.ai_api_key
    if not api_key or api_key == "none":
        try:
            from app.database import async_session_factory
            from app.models.system_config import SystemConfig
            from sqlalchemy import select
            async with async_session_factory() as session:
                res = await session.execute(
                    select(SystemConfig.value).where(SystemConfig.key == "ai.api_key")
                )
                db_val = res.scalar_one_or_none()
                if db_val and db_val.strip():
                    api_key = db_val.strip()
        except Exception as e:
            logger.warning("Failed to read ai.api_key from db: %s", e)
    return api_key


class AISummarizer:
    """Financial statement summarizer backed by any OpenAI-compatible API."""

    def __init__(self) -> None:
        # Last-known health status — updated by ping_provider().
        self._provider_reachable: bool | None = None

    async def _get_client(self) -> AsyncOpenAI:
        """Construct an AsyncOpenAI client from current settings dynamically."""
        return AsyncOpenAI(
            base_url=settings.ai_api_base_url,
            api_key=await _get_api_key(),
        )

    # ------------------------------------------------------------------
    # Health / connectivity
    # ------------------------------------------------------------------

    async def is_configured(self) -> bool:
        """Return True if API base URL and key are set to non-default values."""
        api_key = await _get_api_key()
        return bool(api_key and api_key != "none")

    async def ping_provider(self) -> bool:
        """Send a minimal completion request to verify connectivity and auth.

        Returns True if the provider responded successfully, False otherwise.
        Updates the internal ``_provider_reachable`` flag.
        """
        try:
            client = await self._get_client()
            await client.chat.completions.create(
                model=settings.ai_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            self._provider_reachable = True
            logger.info("AI provider ping succeeded (model=%s)", settings.ai_model)
        except AuthenticationError as exc:
            self._provider_reachable = False
            logger.warning("AI provider auth failed: %s", exc)
        except APIConnectionError as exc:
            self._provider_reachable = False
            logger.warning("AI provider unreachable: %s", exc)
        except OpenAIError as exc:
            # Some providers (e.g. Ollama) return a non-200 on a 1-token ping
            # but are still operational.  Treat anything other than auth/conn
            # errors as "reachable" so we don't block the summarise endpoint.
            self._provider_reachable = True
            logger.info(
                "AI provider ping returned error (treated as reachable): %s", exc
            )
        return bool(self._provider_reachable)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    async def summarize(self, text: str, max_tokens: int = 512) -> SummaryResult:
        """Send text to the LLM and return a structured financial summary."""
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        if len(text) > _MAX_INPUT_CHARS:
            raise ValueError(f"Input text too long (max {_MAX_INPUT_CHARS} characters)")

        try:
            client = await self._get_client()
            response = await client.chat.completions.create(
                model=settings.ai_model,
                messages=[
                    {"role": "system", "content": FINANCIAL_SUMMARIZER_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens,
                temperature=settings.ai_temperature,
                top_p=0.9,
            )
        except OpenAIError as exc:
            logger.error("LLM API call failed: %s", exc)
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        choice = response.choices[0]
        summary = (choice.message.content or "").strip()
        usage = response.usage

        return SummaryResult(
            summary=summary,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        pass


ai_summarizer = AISummarizer()
