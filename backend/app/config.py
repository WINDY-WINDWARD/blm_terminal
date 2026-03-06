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

    # Courtesy delay between consecutive NSE API requests (ms)
    nse_request_delay_ms: int = 500

    # How long cached NSE data is considered fresh (seconds)
    nse_cache_ttl_seconds: int = 300

    # Persistent SQLite cache for historical CSV data
    nse_history_cache_path: str = "./nse_history_cache.db"
    # TTL for cache entries whose to_date is today or in the future (hours)
    nse_history_cache_ttl_hours: int = 12

    log_level: str = "INFO"


settings = Settings()
