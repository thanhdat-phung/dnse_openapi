"""Error types raised by the client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DNSEError(Exception):
    """Base class for every error raised by this package."""


class DNSEValidationError(DNSEError):
    """The request could not be built from the supplied values."""


class DNSEAPIError(DNSEError):
    """DNSE returned a non-2xx response."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        payload: Any = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.code:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " ".join(parts)


class DNSETransportError(DNSEAPIError):
    """Network failure, timeout, or an unreadable response."""


class DNSEAuthError(DNSEAPIError):
    """Credentials, signature, Date header, or permissions were rejected."""


class QuotaExceededError(DNSEAuthError):
    """Daily quota exhausted (HTTP 403, code ``OA-401``)."""


class DNSERateLimitError(DNSEAPIError):
    """Per-hour rate limit exhausted (HTTP 429)."""


class DNSEClientError(DNSEAPIError):
    """A 4xx response that is not specifically classified."""


class DNSEServerError(DNSEAPIError):
    """A 5xx response from DNSE."""


class TradingTokenRequired(DNSEError):
    """No valid trading token is available; authenticate OTP first."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or (
                "No valid trading token. Call auth.create_trading_token(...) "
                "or pass trading_token=... explicitly."
            )
        )


def _extract_fields(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    code = payload.get("code")
    message = payload.get("message")
    return (
        str(code) if code is not None else None,
        str(message) if message is not None else None,
    )


def error_from_response(
    status: int,
    payload: Any,
    *,
    headers: Mapping[str, str] | None = None,
) -> DNSEAPIError:
    """Map an HTTP status and DNSE error body to a typed exception."""
    code, message = _extract_fields(payload)
    request_id = None
    if headers:
        request_id = headers.get("X-Request-Id") or headers.get("x-request-id")

    fallback = {
        400: "Invalid request",
        401: "Authentication failed",
        403: "Forbidden",
        404: "Not found",
        409: "Conflict",
        422: "Unprocessable request",
        429: "Rate limit exceeded",
    }.get(status, f"DNSE request failed with HTTP {status}")
    text = message or fallback

    if status == 429:
        return DNSERateLimitError(
            text, status=status, code=code, payload=payload, request_id=request_id
        )
    if status == 403 and code == "OA-401":
        return QuotaExceededError(
            text, status=status, code=code, payload=payload, request_id=request_id
        )
    if status in (401, 403):
        return DNSEAuthError(
            text, status=status, code=code, payload=payload, request_id=request_id
        )
    if 400 <= status < 500:
        return DNSEClientError(
            text, status=status, code=code, payload=payload, request_id=request_id
        )
    return DNSEServerError(
        text, status=status, code=code, payload=payload, request_id=request_id
    )
