# Load and validate configuration from environment variables

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


DEFAULT_PRODUCT_URL = "https://www.muscleandstrength.com/store/r1-charged-creatine.html"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    product_url: str
    store_view: str
    fetch_mode: str  # "api" | "browser"
    scraper_api_key: str | None
    resend_api_key: str | None
    email_from: str | None
    email_to: str | None
    notify_deal_ended: bool
    heartbeat_enabled: bool
    heartbeat_fail_threshold: int
    scraper_render: bool
    scraper_ultra_premium: bool

    @property
    def can_send_email(self) -> bool:
        return bool(self.resend_api_key and self.email_from and self.email_to)


def load_config() -> Config:
    # Build a Config from the environment and validate the essentials
    cfg = Config(
        product_url=os.getenv("PRODUCT_URL", DEFAULT_PRODUCT_URL).strip(),
        store_view=os.getenv("STORE_VIEW", "us").strip(),
        fetch_mode=os.getenv("FETCH_MODE", "api").strip().lower(),
        scraper_api_key=(os.getenv("SCRAPER_API_KEY") or "").strip() or None,
        resend_api_key=(os.getenv("RESEND_API_KEY") or "").strip() or None,
        email_from=(os.getenv("EMAIL_FROM") or "").strip() or None,
        email_to=(os.getenv("EMAIL_TO") or "").strip() or None,
        notify_deal_ended=_bool(os.getenv("NOTIFY_DEAL_ENDED"), False),
        heartbeat_enabled=_bool(os.getenv("HEARTBEAT_ENABLED"), True),
        heartbeat_fail_threshold=_int(os.getenv("HEARTBEAT_FAIL_THRESHOLD"), 3),
        scraper_render=_bool(os.getenv("SCRAPER_RENDER"), False),
        scraper_ultra_premium=_bool(os.getenv("SCRAPER_ULTRA_PREMIUM"), False),
    )

    if cfg.fetch_mode not in {"api", "browser"}:
        raise ConfigError(
            f"FETCH_MODE must be 'api' or 'browser', got '{cfg.fetch_mode}'"
        )
    if not cfg.product_url:
        raise ConfigError("PRODUCT_URL is required")
    if cfg.fetch_mode == "api" and not cfg.scraper_api_key:
        raise ConfigError("FETCH_MODE=api requires SCRAPER_API_KEY")

    return cfg
