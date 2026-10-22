"""Enums and validated request models for the DNSE OpenAPI.

Request models use camelCase aliases on the wire and accept snake_case keyword
arguments in Python. ``model_dump(mode="json", by_alias=True)`` produces the
payload expected by DNSE.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail if part)


class APIModel(BaseModel):
    """Base model with camelCase aliases and strict unknown-field handling."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class Side(str, Enum):
    BUY = "NB"
    SELL = "NS"


class OrderType(str, Enum):
    LO = "LO"
    MOK = "MOK"
    MAK = "MAK"
    MTL = "MTL"
    ATO = "ATO"
    ATC = "ATC"
    PLO = "PLO"


class MarketType(str, Enum):
    STOCK = "STOCK"
    DERIVATIVE = "DERIVATIVE"
    BOND = "BOND"


class OrderCategory(str, Enum):
    NORMAL = "NORMAL"
    STOP = "STOP"
    OCO = "OCO"


class ConditionOperator(str, Enum):
    GREATER_OR_EQUAL = ">="
    LESS_OR_EQUAL = "<="


class DurationType(str, Enum):
    DAY = "DAY"
    GTD = "GTD"


class OTPType(str, Enum):
    EMAIL = "email_otp"
    SMART = "smart_otp"


class _OrderBase(APIModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Side
    quantity: int = Field(gt=0)
    loan_package_id: int = Field(gt=0)


class NormalOrder(_OrderBase):
    """A regular order (``orderCategory=NORMAL``)."""

    order_category: Literal["NORMAL"] = Field(default="NORMAL", exclude=True)
    order_type: OrderType
    price: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_price(self) -> NormalOrder:
        if self.order_type == OrderType.LO and self.price <= 0:
            raise ValueError("price must be > 0 for LO orders")
        if self.order_type != OrderType.LO and self.price != 0:
            raise ValueError("price must be 0 for non-LO orders (ATO/ATC/MTL/MOK/MAK/PLO)")
        return self


class StopOrder(_OrderBase):
    """A stop order (``orderCategory=STOP``), valid for STOCK and DERIVATIVE."""

    order_category: Literal["STOP"] = Field(default="STOP", exclude=True)
    order_type: Literal["LO", "MTL"] = "LO"
    price: float = Field(ge=0)
    stop_price: float = Field(gt=0)
    condition_operator: ConditionOperator
    duration_type: Literal["GTD"] = "GTD"
    duration_date_time: datetime

    @field_validator("duration_date_time")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("durationDateTime must be timezone-aware (e.g. +07:00)")
        return value

    @field_serializer("duration_date_time")
    def _serialize_duration(self, value: datetime) -> str:
        # DNSE's request example uses millisecond precision.
        return value.isoformat(timespec="milliseconds")

    @model_validator(mode="after")
    def _check_price(self) -> StopOrder:
        if self.order_type == "LO" and self.price <= 0:
            raise ValueError("price must be > 0 for LO stop orders")
        if self.order_type == "MTL" and self.price != 0:
            raise ValueError("price must be 0 for MTL stop orders")
        return self


class OCOOrder(_OrderBase):
    """A one-cancels-the-other order (``orderCategory=OCO``); DERIVATIVE only."""

    order_category: Literal["OCO"] = Field(default="OCO", exclude=True)
    order_type: Literal["LO"] = "LO"
    price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    stop_order_price: float = Field(gt=0)
    duration_type: Literal["DAY"] = "DAY"


class ReplaceOrder(APIModel):
    """Fields accepted by ``PUT /accounts/{accountNo}/orders/{orderId}``.

    DNSE only allows changing price and/or quantity. Derivatives accept one of
    the two per request; stocks accept both (see ``OrderClient.replace_order``).
    """

    price: float | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> ReplaceOrder:
        if self.price is None and self.quantity is None:
            raise ValueError("replace requires at least one of price or quantity")
        return self


class TradingTokenRequest(APIModel):
    otp_type: OTPType
    passcode: str = Field(min_length=4, max_length=12)


AnyOrder = Annotated[NormalOrder | StopOrder | OCOOrder, Field(discriminator="order_category")]

ORDER_MODELS: dict[str, type[NormalOrder] | type[StopOrder] | type[OCOOrder]] = {
    "NORMAL": NormalOrder,
    "STOP": StopOrder,
    "OCO": OCOOrder,
}


def to_vnd(thousands: float) -> float:
    """Convert the thousand-VND prices returned by ``/price/{symbol}/secdef``.

    DNSE's market-data endpoints return stock prices in thousands of VND, while
    order endpoints expect VND (for example ``27.5`` -> ``27500``).
    """
    return float(thousands) * 1000


def order_payload(
    order: NormalOrder | StopOrder | OCOOrder,
) -> dict[str, object]:
    """Serialize an order to the DNSE request body (camelCase, no category)."""
    return order.model_dump(mode="json", by_alias=True, exclude_none=True)
