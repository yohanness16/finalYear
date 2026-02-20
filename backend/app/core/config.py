"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    DATABASE_URL: str = "postgresql://user:pass@localhost:5432/transport_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # AWS (optional for IoT Core)
    AWS_REGION: Optional[str] = "eu-central-1"
    AWS_IOT_ENDPOINT: Optional[str] = None

    # App
    SECRET_KEY: str = "change-me-in-production"
    USE_ML_FOR_PROD: bool = False

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None

    # Data retention (days)
    RAW_TELEMETRY_RETENTION_DAYS: int = 30
    TRIP_HISTORY_RETENTION_DAYS: int = 365

    # Rate limiting (requests per minute per IP)
    RATE_LIMIT_PER_MINUTE: int = 60

    # Google Maps (ETA)
    GOOGLE_MAPS_API_KEY: Optional[str] = None

    # FCM (notifications)
    FCM_SERVER_KEY: Optional[str] = None

    # Redis TTL (seconds)
    BUS_LIVE_TTL: int = 600  # 10 min
    ROUTE_STOP_TTL: int = 300  # 5 min


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
