"""DNSE OpenAPI (LightSpeed) client.

The public entry point is :class:`dnse_openapi.client.DNSEClient`.
"""

from __future__ import annotations

from ._version import __version__
from .client import DNSEClient
from .config import DEFAULT_API_VERSION, DEFAULT_BASE_URL, SANDBOX_BASE_URL, Settings
from .errors import (
    DNSEAPIError,
    DNSEAuthError,
    DNSEClientError,
    DNSEError,
    DNSERateLimitError,
    DNSEServerError,
    DNSETransportError,
    DNSEValidationError,
    QuotaExceededError,
    TradingTokenRequired,
)
from .models import (
    ConditionOperator,
    DurationType,
    MarketType,
    NormalOrder,
    OCOOrder,
    OrderCategory,
    OrderType,
    OTPType,
    ReplaceOrder,
    Side,
    StopOrder,
)
from .otp import EmailOTPReader, OTPTimeout, extract_otp

__all__ = [
    "DNSEClient",
    "DEFAULT_API_VERSION",
    "DEFAULT_BASE_URL",
    "SANDBOX_BASE_URL",
    "Settings",
    "DNSEError",
    "DNSEAPIError",
    "DNSEAuthError",
    "DNSEClientError",
    "DNSERateLimitError",
    "DNSEServerError",
    "DNSETransportError",
    "DNSEValidationError",
    "QuotaExceededError",
    "TradingTokenRequired",
    "ConditionOperator",
    "DurationType",
    "MarketType",
    "NormalOrder",
    "OCOOrder",
    "OrderCategory",
    "OrderType",
    "OTPType",
    "ReplaceOrder",
    "Side",
    "StopOrder",
    "EmailOTPReader",
    "OTPTimeout",
    "extract_otp",
    "__version__",
]
