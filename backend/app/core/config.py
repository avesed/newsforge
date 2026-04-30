"""NewsForge application configuration.

Environment variables for infrastructure and LLM fallback.
LLM provider config is primarily managed via database (admin UI).
Env vars (OPENAI_API_KEY, etc.) serve as fallback when no DB providers exist.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables."""

    # App
    app_name: str = "NewsForge"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://newsforge:newsforge@localhost:5432/newsforge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security — jwt_secret_key is bootstrapped by app.core.secrets, not read here
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    first_admin_email: str | None = None

    # LLM — env vars are fallback only; DB providers (admin UI) take priority
    openai_api_key: str | None = None  # Optional: only needed if no DB providers configured
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Content fetching
    tavily_api_key: str | None = None
    playwright_service_url: str | None = None

    # RSSHub
    rsshub_url: str | None = None
    rsshub_access_key: str | None = None

    # News source API keys
    finnhub_api_key: str | None = None
    newsapi_key: str | None = None

    # StockPulse — fan-out aggregator for per-symbol news
    stockpulse_url: str | None = None
    stockpulse_api_key: str | None = None

    # Pipeline
    pipeline_config_path: str = "config/pipeline.yml"

    # Content storage
    content_storage_path: str = "/app/data/articles"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_pipeline_config(path: str | None = None) -> dict:
    """Load pipeline configuration from YAML file.

    Returns default config if file not found.
    """
    if path is None:
        path = get_settings().pipeline_config_path

    config_path = Path(path)
    if not config_path.is_absolute():
        # Relative to backend directory
        config_path = Path(__file__).parent.parent.parent / config_path

    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}

    return _default_pipeline_config()


def _default_pipeline_config() -> dict:
    """Default pipeline configuration when no YAML file is present."""
    return {
        "categories": {
            "finance": {
                "enable_scoring": True,
                "scoring_threshold": 105,
                "enable_content_fetch": True,
                "enable_deep_analysis": True,
                "enable_entity_extraction": True,
                "entity_types": ["stock", "index", "macro", "person", "org"],
                "enable_sentiment": True,
                "enable_embedding": True,
            },
            "tech": {
                "enable_scoring": True,
                "scoring_threshold": 105,
                "enable_content_fetch": True,
                "enable_deep_analysis": True,
                "enable_entity_extraction": True,
                "entity_types": ["person", "org", "product"],
                "enable_sentiment": True,
                "enable_embedding": True,
            },
            "politics": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": True,
                "entity_types": ["person", "org", "location"],
                "enable_sentiment": True,
                "enable_embedding": False,
            },
            "entertainment": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": True,
                "entity_types": ["person", "org", "product"],
                "enable_sentiment": True,
                "enable_embedding": False,
            },
            "gaming": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": True,
                "entity_types": ["product", "org"],
                "enable_sentiment": True,
                "enable_embedding": False,
            },
            "sports": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": True,
                "entity_types": ["person", "org"],
                "enable_sentiment": True,
                "enable_embedding": False,
            },
            "world": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": True,
                "entity_types": ["person", "org", "location"],
                "enable_sentiment": True,
                "enable_embedding": False,
            },
            "science": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": False,
                "enable_sentiment": False,
                "enable_embedding": False,
            },
            "health": {
                "enable_scoring": False,
                "enable_content_fetch": True,
                "enable_deep_analysis": False,
                "enable_entity_extraction": False,
                "enable_sentiment": False,
                "enable_embedding": False,
            },
            "other": {
                "enable_scoring": False,
                "enable_content_fetch": False,
                "enable_deep_analysis": False,
                "enable_entity_extraction": False,
                "enable_sentiment": False,
                "enable_embedding": False,
            },
        }
    }
