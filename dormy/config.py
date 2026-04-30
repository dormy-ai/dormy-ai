"""Dormy runtime configuration.

Loaded from environment variables (DORMY_ prefix) or .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class DormySettings(BaseSettings):
    """Dormy configuration — see .env.example for all fields."""

    model_config = SettingsConfigDict(
        env_prefix="DORMY_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    # Core
    mode: str = "byok"  # "byok" (user keys) | "dormy_router" (hosted + 5% markup)
    log_level: str = "INFO"

    # Database
    database_url: str | None = None

    # LLM providers
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    mirothinker_api_key: str | None = None

    # External services
    tavily_api_key: str | None = None
    firecrawl_api_key: str | None = None
    stripe_secret_key: str | None = None
    resend_api_key: str | None = None
    telegram_bot_token: str | None = None

    # Local Obsidian vault (for knowledge ingest)
    obsidian_vault_path: str | None = None

    # User identity fallback for CLI / stdio mode (no BYOK request context).
    # When set, dormy.auth.get_current_user_id() returns this UUID.
    # Production HTTP requests resolve user_id from BYOK key hash instead.
    user_id: str | None = None

    # Observability — Telegram chat to receive admin alerts (3+ same-tool
    # errors in 5 min, unhandled exceptions) + periodic digest summaries.
    # Unset = alerts/digest are silently skipped (logged to loguru only).
    alert_chat_id: str | None = None

    # Digest cadence: "weekly" (default, Mondays 09:00 UTC) | "daily"
    # (09:00 UTC) | "off" (disable).
    digest_frequency: str = "weekly"


settings = DormySettings()
