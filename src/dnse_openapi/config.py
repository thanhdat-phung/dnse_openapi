"""Configuration helpers.

Importing the package has no side effects. :meth:`DNSEClient.from_env` may load
a ``.env`` file when ``python-dotenv`` is installed; callers that want full
control can use :meth:`Settings.from_env` with an explicit mapping.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://openapi.dnse.com.vn"
SANDBOX_BASE_URL = "https://sb-openapi.dnse.com.vn"

# Market data is streamed over WebSocket rather than the REST host. Sandbox
# keys are only accepted by the sandbox stream host.
DEFAULT_WS_URL = "wss://ws-openapi.dnse.com.vn"
SANDBOX_WS_URL = "wss://ws-sb-openapi.dnse.com.vn"


def ws_url_for(base_url: str) -> str:
    """Pick the market-data WebSocket host that matches ``base_url``."""
    host = (urlparse(base_url).hostname or "").lower()
    if host.startswith("sb-") or "sandbox" in host:
        return SANDBOX_WS_URL
    return DEFAULT_WS_URL

# Matches the version shipped with the official DNSE sample SDK. Override with
# DNSE_API_VERSION when DNSE publishes a newer version header.
DEFAULT_API_VERSION = "2026-07-23"

# The official SDK sends a different version header for these two endpoints.
# Keep the override (and allow callers to change it) so the client matches the
# SDK's wire behaviour.
SMART_OTP_HANDOFF_VERSION = "2026-01-01"
REVERSE_POSITION_VERSION = "2026-01-01"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration, usually built with :meth:`from_env`."""

    api_key: str
    api_secret: str
    base_url: str = DEFAULT_BASE_URL
    api_version: str = DEFAULT_API_VERSION
    date_header_name: str = "Date"
    account_no: str | None = None
    timeout: float = 30.0
    max_retries: int = 2

    # Market-data stream (derived from base_url when unset)
    ws_url: str | None = None

    # Local server
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    server_token: str | None = None

    # Optional Email OTP automation
    otp_imap_host: str = "imap.gmail.com"
    otp_imap_user: str | None = None
    otp_imap_password: str | None = None
    otp_sender: str | None = "dnse"
    otp_subject: str = "Email OTP"

    debug: bool = False

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError("DNSE_API_KEY and DNSE_API_SECRET are required")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must start with http:// or https://")
        if not self.date_header_name:
            raise ValueError("date_header_name must not be empty")
        if self.ws_url is None:
            object.__setattr__(self, "ws_url", ws_url_for(self.base_url))
        elif not self.ws_url.startswith(("wss://", "ws://")):
            raise ValueError("ws_url must start with wss:// or ws://")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build settings from a mapping (defaults to ``os.environ``)."""
        source = os.environ if env is None else env

        api_key = (source.get("DNSE_API_KEY") or "").strip()
        api_secret = (source.get("DNSE_API_SECRET") or "").strip()
        if not api_key or not api_secret:
            raise ValueError(
                "DNSE_API_KEY and DNSE_API_SECRET must be set "
                "(see .env.example); never hard-code credentials"
            )

        def text(name: str, default: str | None = None) -> str | None:
            value = source.get(name)
            if value is None:
                return default
            value = value.strip()
            return value or default

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            base_url=text("DNSE_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            api_version=text("DNSE_API_VERSION", DEFAULT_API_VERSION) or DEFAULT_API_VERSION,
            date_header_name=text("DNSE_DATE_HEADER", "Date") or "Date",
            account_no=text("DNSE_ACCOUNT_NO"),
            timeout=float(text("DNSE_TIMEOUT", "30") or "30"),
            max_retries=int(text("DNSE_MAX_RETRIES", "2") or "2"),
            ws_url=text("DNSE_WS_URL"),
            server_host=text("DNSE_SERVER_HOST", "127.0.0.1") or "127.0.0.1",
            server_port=int(text("DNSE_SERVER_PORT", "8000") or "8000"),
            server_token=text("DNSE_SERVER_TOKEN"),
            otp_imap_host=text("DNSE_OTP_IMAP_HOST", "imap.gmail.com") or "imap.gmail.com",
            otp_imap_user=text("DNSE_OTP_IMAP_USER"),
            otp_imap_password=text("DNSE_OTP_IMAP_PASSWORD"),
            otp_sender=text("DNSE_OTP_SENDER", "dnse"),
            otp_subject=text("DNSE_OTP_SUBJECT", "Email OTP") or "Email OTP",
            debug=_bool(source.get("DNSE_DEBUG")),
        )

    def with_overrides(self, **kwargs: object) -> Settings:
        """Return a copy with selected fields replaced."""
        return replace(self, **kwargs)  # type: ignore[arg-type]
