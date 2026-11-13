"""Validated settings loaded from environment and .env files."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for CycleScope."""

    model_config = SettingsConfigDict(
        env_prefix="CYCLESCOPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CycleScope"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "sqlite:///data/cyclescope.db"
    log_level: str = "INFO"
    log_directory: Path = Path("logs")
    data_directory: Path = Path("data")
    timezone: str = "UTC"
    api_base_url: str | None = None
    api_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate the Python logging level."""
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                "log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""
    return Settings()
