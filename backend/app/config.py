"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    db_path: str = "./data.db"
    port: int = 4455

    log_level: str = "INFO"

    # Environment mode: development | staging | production
    env: str = "development"

    # JWT secret key for authentication
    secret_key: str = "dev_secret_key_change_in_production"

    @property
    def is_development(self) -> bool:
        """Return True only if running in explicit development/local/testing modes."""
        return self.env.lower().strip() in ("dev", "development", "local", "test", "testing")

    @property
    def is_production(self) -> bool:
        """Return True for any non-development environment (fail-closed default)."""
        return not self.is_development

    # OpenAI-compatible LLM API settings
    ai_api_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = "none"
    ai_model: str = "gpt-4o-mini"
    ai_max_tokens: int = 512
    ai_temperature: float = 0.3

    # OpenCode Zen / MiniMax chat agent settings
    opencode_zen_api_key: str = "none"
    zen_base_url: str = "https://opencode.ai/zen/go/v1"

    # AI Picks Zen API resilience — Phase 1 fix for httpx.ReadTimeout failures.
    # 5 min per-call gives Kimi/MiniMax time to reason over multi-tool results
    # (parallel tool execution + 4096-token generation can exceed 120s easily).
    zen_api_timeout_seconds: float = 300.0
    # Number of retries on ReadTimeout/ConnectTimeout before failing the loop.
    zen_api_max_retries: int = 2
    # Sleep between retries (seconds).
    zen_api_retry_backoff_seconds: float = 5.0

    # Market hours (IST) - for scheduler to determine when to run
    market_start_hour: int = 9
    market_start_minute: int = 15
    market_end_hour: int = 15
    market_end_minute: int = 30

    # Pipeline tuning
    # Sleep between indicator-backfill batches (seconds). Default 0.0
    # (the O(n) rewrite made the sleep pure overhead). Set >0 to throttle
    # DB writes on a busy host.
    indicator_inter_batch_sleep_s: float = 0.0


settings = Settings()
