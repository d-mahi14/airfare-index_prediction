"""
backend/app/config.py
Application configuration loaded from environment / .env file.

Uses pydantic-settings so every field is type-validated at startup.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "airfare_db"
    postgres_user: str = "airfare_user"
    postgres_password: str = "apix_dev_password_2024"

    # --- Application ---
    app_env: str = "development"
    log_level: str = "INFO"
    base_year: int = 2024

    # --- Collection ---
    collection_lead_days_raw: str = "1,7,15,30,45"
    default_currency: str = "INR"
    raw_data_path: str = "data/raw"
    processed_data_path: str = "data/processed"
    reference_data_path: str = "data/reference"

    # --- Rate limiting ---
    scraper_request_delay_seconds: float = 2.0
    scraper_max_retries: int = 3

    # --- AI / LLM (Groq) ---
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_async(self) -> str:
        """Async URL for future asyncpg usage."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def collection_lead_days(self) -> List[int]:
        return [int(d.strip()) for d in self.collection_lead_days_raw.split(",")]

    @property
    def mospi_csv_path(self) -> Path:
        return Path(self.reference_data_path) / "mospi_airfare.csv"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
