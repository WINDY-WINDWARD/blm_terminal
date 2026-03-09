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

    ai_model_path: str | None = None
    ai_max_tokens: int = 512
    ai_n_ctx: int = 8192


settings = Settings()
