"""
AgentZline Application Settings.

Centralized configuration loaded from environment variables via pydantic-settings.
All secrets are loaded from .env — never hardcoded.
"""

from functools import lru_cache

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

    # ── Bronze Tier Thresholds ───────────────────────────────────────────
    DEFAULT_TARGET_ROAS: float = 1.5
    DEFAULT_TARGET_CPA_PKR: float = 500.0
    CPA_SURGE_THRESHOLD_PERCENT: float = 25.0
    BUDGET_CEILING_DAILY_INCREASE_PCT: float = 20.0


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — call this instead of instantiating Settings directly."""
    return Settings()
