"""Application configuration via pydantic-settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    db_path: str = "./data.db"
    port: int = 4455

    # Courtesy delay between consecutive NSE API requests (ms)
    nse_request_delay_ms: int = 500

    # How long cached NSE data is considered fresh (seconds)
    nse_cache_ttl_seconds: int = 300

    log_level: str = "INFO"


settings = Settings()
