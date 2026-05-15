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

    # Live position age cutoff (seconds)
    LIVE_POSITION_MAX_AGE_SECONDS: int = 180

    # --- Security ---
    # Allowed CORS origins (comma-separated). "*" = allow all (dev only).
    CORS_ORIGINS: str = "*"

    # Firewall blocklist file path
    BLOCKLIST_PATH: str = "storage/firewall_blocklist.txt"

    # Firewall anomaly thresholds
    FIREWALL_AUTO_BAN_THRESHOLD: int = 100
    FIREWALL_AUTO_BAN_WINDOW_SECONDS: int = 300
    FIREWALL_AUTO_BAN_DURATION_SECONDS: int = 3600
    FIREWALL_BURST_THRESHOLD: int = 50
    FIREWALL_BURST_WINDOW_SECONDS: int = 10

    # Request validation
    MAX_JSON_BODY_BYTES: int = 1_048_576       # 1 MB
    MAX_MULTIPART_BODY_BYTES: int = 10_485_760  # 10 MB
    MAX_FORM_BODY_BYTES: int = 524_288          # 512 KB

    # HSTS max-age in seconds (1 year)
    HSTS_MAX_AGE: int = 31_536_000

    # Enable/disable firewall middleware
    FIREWALL_ENABLED: bool = True

    # Trust X-Forwarded-For from these proxy IPs (comma-separated)
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    # --- Email (Resend) ---
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "noreply@bustrack.dpdns.org"
    # Base URL of the frontend app (for verification/reset links)
    APP_BASE_URL: str = "https://bustrack.dpdns.org"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
