from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./worldcap.db"
    football_data_api_key: str = ""
    digest_output_dir: Path = Path("./output")
    whatsapp_pickup_path: Path = Path("./output/latest.md")
    daily_refresh_cron: str = "0 9 * * *"
    log_level: str = "INFO"

    # Claude SDK
    anthropic_api_key: str = ""
    sentiment_model: str = "claude-haiku-4-5"
    rationale_model: str = "claude-sonnet-4-5"
    rationale_token_budget: int = 100_000
    rationale_horizon_days: int = 14

    # News
    gnews_api_key: str = ""

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "worldcap/0.1"

    competition_code: str = "WC"  # football-data.org API code
    db_competition_code: str = "WC2026"  # internal/seed code (distinct from competition_code)


@lru_cache
def get_settings() -> Settings:
    return Settings()
