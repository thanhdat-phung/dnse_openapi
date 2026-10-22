"""Trading-token (2FA) handling and pluggable token stores."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .config import SMART_OTP_HANDOFF_VERSION
from .errors import DNSEAPIError, TradingTokenRequired
from .models import OTPType, TradingTokenRequest
from .transport import APIResponse, Transport

DEFAULT_TOKEN_TTL = 8 * 60 * 60  # DNSE trading tokens are valid for 8 hours

@runtime_checkable
class TokenStore(Protocol):
    """Persistence for the short-lived trading token."""

    def load(self) -> tuple[str, float] | None:
        """Return ``(token, expires_at_epoch)`` or ``None``."""

    def save(self, token: str, expires_at: float) -> None:
        """Persist a token and its expiry."""

    def clear(self) -> None:
        """Remove any stored token."""


class MemoryTokenStore:
    """Default in-process store. Tokens are lost when the process exits."""

    def __init__(self) -> None:
        self._entry: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def load(self) -> tuple[str, float] | None:
        with self._lock:
            return self._entry

    def save(self, token: str, expires_at: float) -> None:
        with self._lock:
            self._entry = (token, expires_at)

    def clear(self) -> None:
        with self._lock:
            self._entry = None


class FileTokenStore:
    """Optional encrypted-at-rest-by-you token cache.

    The file is written atomically with owner-only permissions where the
    platform supports it. Prefer the in-memory store unless a long-running
    process needs to survive restarts: a trading token is a bearer credential.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()

    def load(self) -> tuple[str, float] | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        token = payload.get("trading_token")
        expires_at = payload.get("expires_at")
        if not isinstance(token, str) or not isinstance(expires_at, (int, float)):
            return None
        return token, float(expires_at)

    def save(self, token: str, expires_at: float) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"trading_token": token, "expires_at": expires_at}),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)
        if os.name == "posix":
            os.chmod(self._path, 0o600)

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path.unlink()


class AuthClient:
    """Email/Smart OTP flows and the trading-token cache."""

    def __init__(
        self,
        transport: Transport,
        *,
        store: TokenStore | None = None,
        ttl: float = DEFAULT_TOKEN_TTL,
        safety_margin: float = 60.0,
        clock: Any = time.time,
    ) -> None:
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if safety_margin < 0:
            raise ValueError("safety_margin must be >= 0")
        self._transport = transport
        self._store = store or MemoryTokenStore()
        self._ttl = ttl
        self._safety_margin = safety_margin
        self._clock = clock

    # -- OTP requests -------------------------------------------------------

    def send_email_otp(self) -> APIResponse:
        """Ask DNSE to email a one-time passcode to the registered address."""
        return self._transport.post("/registration/send-email-otp")

    def create_smart_otp_handoff(self, *, version: str = SMART_OTP_HANDOFF_VERSION) -> APIResponse:
        """Trigger the DNSE app confirmation popup and return the response.

        The response contains ``smartOtp``; DNSE holds the request open until the
        user confirms, so the read timeout is raised to 330 seconds.

        The official SDK pins this endpoint to API version ``2026-01-01``; the
        override is kept here but can be changed per call.
        """
        return self._transport.post(
            "/registration/smart-otp/handoff",
            timeout=330.0,
            version=version,
        )

    def request_smart_otp(self) -> str:
        """Convenience wrapper returning the ``smartOtp`` code from handoff."""
        response = self.create_smart_otp_handoff()
        token = (response.data or {}).get("smartOtp") if isinstance(response.data, dict) else None
        if not token:
            raise DNSEAPIError("smart OTP handoff returned no 'smartOtp' value")
        return str(token)

    # -- trading token ------------------------------------------------------

    def create_trading_token(
        self,
        otp_type: OTPType | str,
        passcode: str,
        *,
        ttl: float | None = None,
    ) -> str:
        """Exchange an OTP for a trading token and cache it."""
        request = TradingTokenRequest(otp_type=OTPType(otp_type), passcode=passcode)
        response = self._transport.post(
            "/registration/trading-token",
            json_body=request.model_dump(mode="json", by_alias=True),
        )
        token = None
        if isinstance(response.data, dict):
            # Production/spec responses use ``tradingToken``. The sandbox guide
            # shows ``trading-token``; accept both so a server rename cannot
            # silently break the cache.
            token = response.data.get("tradingToken") or response.data.get("trading-token")
        if not token:
            raise DNSEAPIError("trading-token response did not contain 'tradingToken'")
        self.set_trading_token(str(token), ttl=ttl)
        return str(token)

    def set_trading_token(self, token: str, *, ttl: float | None = None) -> None:
        """Cache a token obtained elsewhere (for example another process)."""
        if not token:
            raise ValueError("token must not be empty")
        lifetime = self._ttl if ttl is None else ttl
        self._store.save(token, self._clock() + lifetime)

    def get_trading_token(self) -> str:
        """Return a cached token or raise :class:`TradingTokenRequired`."""
        entry = self._store.load()
        if entry is None:
            raise TradingTokenRequired()
        token, expires_at = entry
        if expires_at - self._safety_margin <= self._clock():
            self._store.clear()
            raise TradingTokenRequired(
                "Trading token expired. Re-authenticate with OTP to obtain a new one."
            )
        return token

    def has_valid_token(self) -> bool:
        try:
            self.get_trading_token()
        except TradingTokenRequired:
            return False
        return True

    @property
    def expires_at(self) -> float | None:
        entry = self._store.load()
        return entry[1] if entry else None

    def clear(self) -> None:
        self._store.clear()
