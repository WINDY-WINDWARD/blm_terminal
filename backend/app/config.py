"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    db_path: str = "./data.db"
    port: int = 4455

    log_level: str = "INFO"

    # OpenAI-compatible LLM API settings
    ai_api_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = "none"
    ai_model: str = "gpt-4o-mini"
    ai_max_tokens: int = 512
    ai_temperature: float = 0.3


settings = Settings()
