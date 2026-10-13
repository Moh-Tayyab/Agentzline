"""
AgentZline Application Settings.

Centralized configuration loaded from environment variables via pydantic-settings.
All secrets are loaded from .env — never hardcoded.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable binding."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "AgentZline"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    # ── Database ─────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://agentzline:changeme@localhost:5432/agentzline"
    DATABASE_ECHO: bool = False

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Accept Render-style postgres:// URLs by mapping them to asyncpg driver."""
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # ── Encryption (Fernet for token vault) ──────────────────────────────
    FERNET_ENCRYPTION_KEY: str = "CHANGE_ME_TO_A_REAL_FERNET_KEY"

    # ── Meta Graph API ───────────────────────────────────────────────────
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_SYSTEM_USER_TOKEN: str = ""
    META_BUSINESS_ID: str = ""
    META_API_VERSION: str = "v19.0"

    # ── WhatsApp Business API ────────────────────────────────────────────
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""
    WHATSAPP_WEBHOOK_PORT: int = 8000

    # ── Anthropic API ────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # ── Scheduling ───────────────────────────────────────────────────────
    DAILY_REPORT_TIME: str = "09:00"
    REPORT_TIMEZONE: str = "Asia/Karachi"
    SCHEDULER_JITTER_MAX_SECONDS: int = 300  # Spread window (0-300s) to prevent 9 AM thundering herd
    TOKEN_EXPIRY_WARNING_DAYS: int = 7  # Warn when credential expires within this window

    # ── Bronze Tier Thresholds ───────────────────────────────────────────
    DEFAULT_TARGET_ROAS: float = 1.5
    DEFAULT_TARGET_CPA_PKR: float = 500.0
    CPA_SURGE_THRESHOLD_PERCENT: float = 25.0
    BUDGET_CEILING_DAILY_INCREASE_PCT: float = 20.0

    # ── Phase-2 Intraday Pacing Alerts ─────────────────────────────────────
    INTRADAY_BLEED_SPEND_RATIO: float = 0.5  # Alert when intraday spend > 50% of daily budget
    INTRADAY_BLEED_CTR_THRESHOLD: float = 0.6  # ... with zero conversions and CTR below this %
    INTRADAY_SUPPRESSION_HOURS: int = 24  # Max 1 pacing alert per campaign per window

    # ── Security & CORS ──────────────────────────────────────────────────
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3000"

    # ── Phase-3 Silver Tier HITL Action Tokens ──────────────────────────────
    ACTION_TOKEN_SECRET: str = ""  # If empty, falls back to FERNET_ENCRYPTION_KEY / META_APP_SECRET
    ACTION_TOKEN_EXPIRY_MINUTES: int = 15  # TTL for interactive WhatsApp buttons

    # ── Phase-4 Gold Tier Courier Webhook Security ──────────────────────────
    COURIER_WEBHOOK_SECRET: str = ""  # Shared secret token for PostEx/Trax/Leopards/Swyft webhooks

    def get_cors_origins(self) -> list[str]:
        """Parse comma-separated allowed origins."""
        if not self.CORS_ALLOWED_ORIGINS:
            return ["http://localhost:3000", "http://localhost:8000"]
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — call this instead of instantiating Settings directly."""
    return Settings()
