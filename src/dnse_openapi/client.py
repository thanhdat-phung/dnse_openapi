"""High-level DNSE OpenAPI client."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import httpx

from .accounts import AccountClient
from .auth import AuthClient, TokenStore
from .config import DEFAULT_API_VERSION, DEFAULT_BASE_URL, Settings, ws_url_for
from .errors import DNSEValidationError
from .models import (
    MarketType,
    NormalOrder,
    OCOOrder,
    OTPType,
    StopOrder,
)
from .orders import OrderClient
from .otp import EmailOTPReader
from .signing import DEFAULT_ALGORITHM
from .stream import MarketStream
from .transport import Transport


class DNSEClient:
    """Entry point for the DNSE OpenAPI.

    ``auth`` exposes the OTP/trading-token flow, ``accounts`` the read endpoints
    and ``orders`` the mutating ones. Credentials are only ever held in memory.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
        date_header_name: str = "Date",
        algorithm: str = DEFAULT_ALGORITHM,
        account_no: str | None = None,
        ws_url: str | None = None,
        token_store: TokenStore | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
        otp_reader: EmailOTPReader | None = None,
        auth_clock: Callable[[], float] | None = None,
        date_provider: Callable[[], datetime | str] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.account_no = account_no
        self._ws_url = ws_url or ws_url_for(base_url)
        self._api_key = api_key
        self._api_secret = api_secret
        self.transport = Transport(
            api_key,
            api_secret,
            base_url=base_url,
            api_version=api_version,
            date_header_name=date_header_name,
            algorithm=algorithm,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
            clock=date_provider,
            sleep=sleep,
        )
        self.auth = AuthClient(
            self.transport,
            store=token_store,
            clock=auth_clock or time.time,
        )
        self.accounts = AccountClient(self.transport)
        self.orders = OrderClient(self.transport, self.auth)
        self._otp_reader = otp_reader

    # -- construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
        **overrides: Any,
    ) -> DNSEClient:
        """Build a client from ``DNSE_*`` environment variables.

        When ``env`` is omitted and ``python-dotenv`` is installed, a ``.env``
        file in the current directory (or a parent) is loaded first. Importing
        the package itself has no file-system side effects.
        """
        if env is None and load_env_file:
            try:
                from dotenv import find_dotenv, load_dotenv
            except ImportError:  # core install without the optional extra
                pass
            else:
                dotenv_path = find_dotenv(usecwd=True)
                if dotenv_path:
                    load_dotenv(dotenv_path)
        return cls.from_settings(Settings.from_env(env), **overrides)

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> DNSEClient:
        """Build a client from an explicit :class:`Settings` instance."""
        reader = None
        if settings.otp_imap_user and settings.otp_imap_password:
            reader = EmailOTPReader(
                settings.otp_imap_user,
                settings.otp_imap_password,
                host=settings.otp_imap_host,
                sender=settings.otp_sender,
                subject=settings.otp_subject,
            )
        values: dict[str, Any] = {
            "api_key": settings.api_key,
            "api_secret": settings.api_secret,
            "base_url": settings.base_url,
            "api_version": settings.api_version,
            "date_header_name": settings.date_header_name,
            "account_no": settings.account_no,
            "ws_url": settings.ws_url,
            "timeout": settings.timeout,
            "max_retries": settings.max_retries,
            "otp_reader": reader,
        }
        values.update(overrides)
        return cls(**values)

    # -- authentication -----------------------------------------------------

    def login_with_email_otp(
        self,
        reader: EmailOTPReader | None = None,
        *,
        timeout: float = 180.0,
        poll_interval: float = 2.0,
    ) -> str:
        """Send an Email OTP, read it over IMAP, and cache the trading token."""
        otp_reader = reader or self._otp_reader
        if otp_reader is None:
            raise DNSEValidationError(
                "no EmailOTPReader configured; pass reader=... or set "
                "DNSE_OTP_IMAP_USER/DNSE_OTP_IMAP_PASSWORD"
            )
        requested_at = time.time()
        self.auth.send_email_otp()
        passcode = otp_reader.wait_for_otp(
            timeout=timeout, poll_interval=poll_interval, after=requested_at
        )
        return self.auth.create_trading_token(OTPType.EMAIL, passcode)

    def login_with_smart_otp(self, passcode: str) -> str:
        """Exchange a Smart OTP copied from the DNSE app."""
        return self.auth.create_trading_token(OTPType.SMART, passcode)

    def login_with_handoff(self) -> str:
        """Trigger the DNSE app popup, then exchange the returned Smart OTP."""
        passcode = self.auth.request_smart_otp()
        return self.auth.create_trading_token(OTPType.SMART, passcode)

    # -- order conveniences -------------------------------------------------

    def require_account_no(self, account_no: str | None = None) -> str:
        value = account_no or self.account_no
        if not value:
            raise DNSEValidationError(
                "account_no is required; pass it explicitly or set DNSE_ACCOUNT_NO"
            )
        return value

    def place_order(
        self,
        order: NormalOrder | StopOrder | OCOOrder,
        *,
        account_no: str | None = None,
        market_type: MarketType | str = MarketType.STOCK,
        trading_token: str | None = None,
    ) -> Any:
        return self.orders.place_order(
            self.require_account_no(account_no),
            market_type,
            order,
            trading_token=trading_token,
        )

    # -- lifecycle ----------------------------------------------------------

    def market_stream(self, **overrides: Any) -> MarketStream:
        """Return a market-data WebSocket client for these credentials.

        The stream is not connected until it is awaited or used as an async
        context manager::

            async with client.market_stream() as stream:
                ...
        """
        overrides.setdefault("url", self._ws_url)
        return MarketStream(self._api_key, self._api_secret, **overrides)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> DNSEClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
