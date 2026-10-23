"""DNSE OpenAPI (LightSpeed) client.

The public entry point is :class:`dnse_openapi.client.DNSEClient`.
"""

from __future__ import annotations

from ._version import __version__
from .client import DNSEClient
from .config import (
    DEFAULT_API_VERSION,
    DEFAULT_BASE_URL,
    DEFAULT_WS_URL,
    SANDBOX_BASE_URL,
    SANDBOX_WS_URL,
    Settings,
)
from .errors import (
    DNSEAPIError,
    DNSEAuthError,
    DNSEClientError,
    DNSEError,
    DNSERateLimitError,
    DNSEServerError,
    DNSEStreamError,
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
from .stream import (
    MarketStream,
    auth_payload,
    estimated_market_index_channel,
    expected_price_channel,
    foreign_channel,
    market_index_channel,
    ohlc_channel,
    security_definition_channel,
    session_channel,
    tick_channel,
    tick_extra_channel,
    top_price_channel,
)

__all__ = [
    "DNSEClient",
    "DEFAULT_API_VERSION",
    "DEFAULT_BASE_URL",
    "DEFAULT_WS_URL",
    "SANDBOX_BASE_URL",
    "SANDBOX_WS_URL",
    "Settings",
    "DNSEError",
    "DNSEAPIError",
    "DNSEAuthError",
    "DNSEClientError",
    "DNSERateLimitError",
    "DNSEServerError",
    "DNSEStreamError",
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
    "MarketStream",
    "auth_payload",
    "tick_channel",
    "tick_extra_channel",
    "top_price_channel",
    "expected_price_channel",
    "security_definition_channel",
    "ohlc_channel",
    "market_index_channel",
    "estimated_market_index_channel",
    "foreign_channel",
    "session_channel",
    "__version__",
]
