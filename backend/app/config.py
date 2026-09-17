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
    log_dir: str = ""
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

    # AI Provider: "zen-free" | "zen-paid" | "go" | "gemini" | "aistudio" | "groq" | "nvidia"
    #   | "anthropic" | "claude-code" | "openai" | "openrouter" | "deepseek" | "xai"
    #   | "together" | "copilot" | "codex"
    # ("zen" is a legacy alias resolved to zen-paid/zen-free in ai_config.py)
    ai_provider: str = "zen-free"

    # OpenCode Zen / MiniMax chat agent settings
    opencode_zen_api_key: str = "none"
    zen_base_url: str = "https://opencode.ai/zen/go/v1"

    # Google AI Studio (Gemini API), Groq, and NVIDIA NIM keys — DB slots
    # ai.aistudio_api_key / ai.groq_api_key / ai.nvidia_api_key take
    # precedence when set.
    aistudio_api_key: str = "none"
    groq_api_key: str = "none"
    nvidia_api_key: str = "none"

    # --- Multi-provider keys (DB slots ai.<name> take precedence when set) ---
    anthropic_api_key: str = "none"       # direct Anthropic API key
    claude_code_oauth_token: str = "none"  # sk-ant-oat01… token from `claude setup-token`
    openai_api_key: str = "none"           # direct OpenAI API key
    openrouter_api_key: str = "none"       # OpenRouter API key
    deepseek_api_key: str = "none"         # DeepSeek API key
    xai_api_key: str = "none"              # xAI (Grok) API key
    together_api_key: str = "none"         # Together AI API key
    copilot_gh_token: str = "none"         # GitHub token (COPILOT_GITHUB_TOKEN)
    gh_token: str = "none"                 # fallback alias (GH_TOKEN / GITHUB_TOKEN)

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
