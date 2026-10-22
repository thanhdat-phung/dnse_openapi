"""Order placement, replacement, cancellation and position actions."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .auth import AuthClient
from .config import REVERSE_POSITION_VERSION
from .errors import DNSEValidationError
from .models import (
    ORDER_MODELS,
    MarketType,
    NormalOrder,
    OCOOrder,
    OrderCategory,
    ReplaceOrder,
    StopOrder,
    order_payload,
)
from .transport import Transport


def _seg(value: object) -> str:
    return quote(str(value), safe="")


def _market(value: MarketType | str) -> MarketType:
    try:
        return MarketType(value)
    except ValueError as exc:
        raise DNSEValidationError(f"unsupported marketType: {value!r}") from exc


def _category(value: OrderCategory | str) -> OrderCategory:
    try:
        return OrderCategory(value)
    except ValueError as exc:
        raise DNSEValidationError(f"unsupported orderCategory: {value!r}") from exc


class OrderClient:
    """Trading endpoints. Every mutating call requires a trading token."""

    def __init__(self, transport: Transport, auth: AuthClient) -> None:
        self._transport = transport
        self._auth = auth

    # -- helpers ------------------------------------------------------------

    def _token(self, trading_token: str | None) -> str:
        return trading_token or self._auth.get_trading_token()

    @staticmethod
    def _validate_market(market_type: MarketType, category: OrderCategory) -> None:
        if category is OrderCategory.OCO and market_type is not MarketType.DERIVATIVE:
            raise DNSEValidationError("OCO orders are only supported for DERIVATIVE")
        if category is OrderCategory.STOP and market_type is MarketType.BOND:
            raise DNSEValidationError("STOP orders are not supported for BOND")

    # -- place --------------------------------------------------------------

    def place_order(
        self,
        account_no: str,
        market_type: MarketType | str,
        order: NormalOrder | StopOrder | OCOOrder,
        *,
        trading_token: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Place a validated NORMAL, STOP or OCO order."""
        if not account_no:
            raise DNSEValidationError("account_no is required")
        market = _market(market_type)
        category = _category(order.order_category)
        self._validate_market(market, category)

        response = self._transport.post(
            f"/accounts/{_seg(account_no)}/orders",
            params={"marketType": market, "orderCategory": category},
            json_body=order_payload(order),
            headers={"trading-token": self._token(trading_token)},
            timeout=timeout,
        )
        return response.data

    def place_raw(
        self,
        account_no: str,
        market_type: MarketType | str,
        order_category: OrderCategory | str,
        payload: dict[str, Any],
        *,
        trading_token: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Validate a raw DNSE body against the model for ``order_category``.

        Useful for servers and for features that are added to DNSE before this
        package gets a dedicated model.
        """
        category = _category(order_category)
        model = ORDER_MODELS[category.value]
        order = model.model_validate(payload)
        return self.place_order(
            account_no,
            market_type,
            order,
            trading_token=trading_token,
            timeout=timeout,
        )

    def place_normal(
        self,
        account_no: str,
        market_type: MarketType | str,
        *,
        trading_token: str | None = None,
        **fields: Any,
    ) -> Any:
        order = NormalOrder(**fields)
        return self.place_order(
            account_no, market_type, order, trading_token=trading_token
        )

    def place_stop(
        self,
        account_no: str,
        market_type: MarketType | str,
        *,
        trading_token: str | None = None,
        **fields: Any,
    ) -> Any:
        order = StopOrder(**fields)
        return self.place_order(
            account_no, market_type, order, trading_token=trading_token
        )

    def place_oco(
        self,
        account_no: str,
        market_type: MarketType | str,
        *,
        trading_token: str | None = None,
        **fields: Any,
    ) -> Any:
        order = OCOOrder(**fields)
        return self.place_order(
            account_no, market_type, order, trading_token=trading_token
        )

    # -- replace / cancel ---------------------------------------------------

    def replace_order(
        self,
        account_no: str,
        order_id: str,
        market_type: MarketType | str,
        replacement: ReplaceOrder | dict[str, Any],
        *,
        order_category: OrderCategory | str = OrderCategory.NORMAL,
        trading_token: str | None = None,
    ) -> Any:
        """Replace price/quantity of an existing NORMAL order."""
        market = _market(market_type)
        category = _category(order_category)
        if category is not OrderCategory.NORMAL:
            raise DNSEValidationError("only NORMAL orders can be replaced")
        model = (
            replacement
            if isinstance(replacement, ReplaceOrder)
            else ReplaceOrder.model_validate(replacement)
        )
        if (
            market is MarketType.DERIVATIVE
            and model.price is not None
            and model.quantity is not None
        ):
            raise DNSEValidationError(
                "DERIVATIVE orders accept only one of price or quantity per replace"
            )
        response = self._transport.put(
            f"/accounts/{_seg(account_no)}/orders/{_seg(order_id)}",
            params={"marketType": market, "orderCategory": category},
            json_body=model.model_dump(mode="json", by_alias=True, exclude_none=True),
            headers={"trading-token": self._token(trading_token)},
        )
        return response.data

    def cancel_order(
        self,
        account_no: str,
        order_id: str,
        market_type: MarketType | str,
        *,
        order_category: OrderCategory | str = OrderCategory.NORMAL,
        trading_token: str | None = None,
    ) -> Any:
        """Cancel a NORMAL order, or a STOP/OCO order that is still ``New``."""
        market = _market(market_type)
        category = _category(order_category)
        response = self._transport.delete(
            f"/accounts/{_seg(account_no)}/orders/{_seg(order_id)}",
            params={"marketType": market, "orderCategory": category},
            headers={"trading-token": self._token(trading_token)},
        )
        return response.data

    # -- positions ----------------------------------------------------------

    def close_position(
        self,
        position_id: str,
        market_type: MarketType | str = MarketType.DERIVATIVE,
        *,
        trading_token: str | None = None,
    ) -> Any:
        market = _market(market_type)
        return self._transport.post(
            f"/positions/{_seg(position_id)}/close",
            params={"marketType": market},
            headers={"trading-token": self._token(trading_token)},
        ).data

    def reverse_position(
        self,
        position_id: str,
        *,
        trading_token: str | None = None,
        version: str = REVERSE_POSITION_VERSION,
    ) -> Any:
        # The official SDK pins reverse-position to API version 2026-01-01.
        return self._transport.post(
            f"/positions/{_seg(position_id)}/reverse",
            params={"marketType": MarketType.DERIVATIVE},
            headers={"trading-token": self._token(trading_token)},
            version=version,
        ).data

    # -- PnL configuration --------------------------------------------------

    def set_position_pnl_config(
        self,
        position_id: str,
        payload: dict[str, Any],
        *,
        market_type: MarketType | str = MarketType.DERIVATIVE,
        trading_token: str | None = None,
    ) -> Any:
        return self._transport.post(
            f"/positions/{_seg(position_id)}/pnl-configs",
            params={"marketType": _market(market_type)},
            json_body=payload,
            headers={"trading-token": self._token(trading_token)},
        ).data

    def patch_account_pnl_config(
        self,
        account_no: str,
        payload: dict[str, Any],
        *,
        market_type: MarketType | str = MarketType.DERIVATIVE,
        trading_token: str | None = None,
    ) -> Any:
        return self._transport.request(
            "PATCH",
            f"/accounts/{_seg(account_no)}/pnl-configs",
            params={"marketType": _market(market_type)},
            json_body=payload,
            headers={"trading-token": self._token(trading_token)},
        ).data
