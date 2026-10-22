"""Read-side endpoints: accounts, orders, positions and market data."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .models import MarketType, OrderCategory
from .transport import APIResponse, Transport


def _seg(value: object) -> str:
    return quote(str(value), safe="")


class AccountClient:
    """Thin, typed wrappers around DNSE's read endpoints."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    # -- accounts -----------------------------------------------------------

    def get_accounts(self) -> Any:
        """Return the investor profile; sub-accounts are in ``payload["accounts"]``."""
        return self._transport.get("/accounts").data

    def get_balances(self, account_no: str) -> Any:
        """Return the stock/derivative/bond/egg balance sections for an account."""
        return self._transport.get(f"/accounts/{_seg(account_no)}/balances").data

    def get_loan_packages(
        self,
        account_no: str,
        market_type: MarketType | str = MarketType.STOCK,
        symbol: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/loan-packages",
            params={"marketType": market_type, "symbol": symbol},
        ).data

    def get_loans(
        self,
        account_no: str,
        market_type: MarketType | str = MarketType.STOCK,
        *,
        disbursement_from: str | None = None,
        disbursement_to: str | None = None,
        due_date_from: str | None = None,
        due_date_to: str | None = None,
        position_id: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/loans",
            params={
                "marketType": market_type,
                "disbursementFrom": disbursement_from,
                "disbursementTo": disbursement_to,
                "dueDateFrom": due_date_from,
                "dueDateTo": due_date_to,
                "positionId": position_id,
                "pageIndex": page_index,
                "pageSize": page_size,
            },
        ).data

    def get_ppse(
        self,
        account_no: str,
        symbol: str,
        price: float,
        loan_package_id: int,
        market_type: MarketType | str = MarketType.STOCK,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/ppse",
            params={
                "marketType": market_type,
                "symbol": symbol,
                "price": price,
                "loanPackageId": loan_package_id,
            },
        ).data

    # -- positions ----------------------------------------------------------

    def get_positions(
        self,
        account_no: str,
        market_type: MarketType | str = MarketType.STOCK,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/positions",
            params={"marketType": market_type},
        ).data

    def get_position(self, position_id: str, market_type: MarketType | str) -> Any:
        return self._transport.get(
            f"/positions/{_seg(position_id)}",
            params={"marketType": market_type},
        ).data

    def get_position_pnl_configs(
        self, position_id: str, market_type: MarketType | str
    ) -> Any:
        return self._transport.get(
            f"/positions/{_seg(position_id)}/pnl-configs",
            params={"marketType": market_type},
        ).data

    def get_account_pnl_configs(
        self, account_no: str, market_type: MarketType | str = MarketType.DERIVATIVE
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/pnl-configs",
            params={"marketType": market_type},
        ).data

    # -- orders -------------------------------------------------------------

    def get_orders(
        self,
        account_no: str,
        market_type: MarketType | str,
        order_category: OrderCategory | str = OrderCategory.NORMAL,
        *,
        page_index: int = 0,
        page_size: int = 10,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/orders",
            params={
                "marketType": market_type,
                "orderCategory": order_category,
                "pageIndex": page_index,
                "pageSize": page_size,
            },
        ).data

    def get_order_detail(
        self,
        account_no: str,
        order_id: str,
        market_type: MarketType | str,
        order_category: OrderCategory | str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/orders/{_seg(order_id)}",
            params={"marketType": market_type, "orderCategory": order_category},
        ).data

    def get_execution_detail(
        self,
        account_no: str,
        order_id: str,
        market_type: MarketType | str,
        order_category: OrderCategory | str = OrderCategory.NORMAL,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/executions/{_seg(order_id)}",
            params={"marketType": market_type, "orderCategory": order_category},
        ).data

    def get_order_history(
        self,
        account_no: str,
        market_type: MarketType | str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/orders/history",
            params={
                "marketType": market_type,
                "from": from_date,
                "to": to_date,
                "pageIndex": page_index,
                "pageSize": page_size,
            },
        ).data

    def get_corporate_action_history(
        self,
        account_no: str,
        *,
        symbol: str | None = None,
        ca_type: str | None = None,
        ca_status: str | None = None,
        page_index: int | None = None,
        page_size: int | None = None,
    ) -> Any:
        return self._transport.get(
            f"/accounts/{_seg(account_no)}/corporate-action-history",
            params={
                "symbol": symbol,
                "caType": ca_type,
                "caStatus": ca_status,
                "pageIndex": page_index,
                "pageSize": page_size,
            },
        ).data

    # -- market data --------------------------------------------------------

    def get_security_definition(self, symbol: str, board_id: str | None = None) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/secdef",
            params={"boardId": board_id},
        ).data

    def get_ohlc(self, bar_type: str, query: dict[str, Any] | None = None) -> Any:
        """Return OHLCV candles from ``GET /price/ohlc``.

        ``bar_type`` is the market type (``STOCK``, ``DERIVATIVE`` or ``INDEX``),
        not the candle size. ``query`` must contain ``symbol``, ``resolution``,
        ``from`` and ``to`` (Unix seconds). Resolution is one of ``1``, ``3``,
        ``5``, ``15``, ``30``, ``1h``, ``1D`` or ``1W``.
        """
        params = dict(query or {})
        params["type"] = bar_type
        return self._transport.get("/price/ohlc", params=params).data

    def get_trades(
        self,
        symbol: str,
        *,
        board_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        next_page_token: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/trades",
            params={
                "boardId": board_id,
                "from": from_date,
                "to": to_date,
                "limit": limit,
                "order": order,
                "nextPageToken": next_page_token,
            },
        ).data

    def get_latest_trade(self, symbol: str, board_id: str | None = None) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/trades/latest",
            params={"boardId": board_id},
        ).data

    def get_trades_volume_profile(
        self, symbol: str, time: str, board_id: str | None = None
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/trades/volume-profile",
            params={"time": time, "boardId": board_id},
        ).data

    def get_quotes(
        self,
        symbol: str,
        *,
        board_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        next_page_token: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/quotes",
            params={
                "boardId": board_id,
                "from": from_date,
                "to": to_date,
                "limit": limit,
                "order": order,
                "nextPageToken": next_page_token,
            },
        ).data

    def get_latest_quote(self, symbol: str, board_id: str | None = None) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/quotes/latest",
            params={"boardId": board_id},
        ).data

    def get_expected_price(
        self,
        symbol: str,
        *,
        board_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        next_page_token: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/expected-price",
            params={
                "boardId": board_id,
                "from": from_date,
                "to": to_date,
                "limit": limit,
                "order": order,
                "nextPageToken": next_page_token,
            },
        ).data

    def get_close_price(self, symbol: str, board_id: str | None = None) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/close",
            params={"boardId": board_id},
        ).data

    def get_foreign_trading(
        self,
        symbol: str,
        *,
        board_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        next_page_token: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(symbol)}/foreign-trading",
            params={
                "boardId": board_id,
                "from": from_date,
                "to": to_date,
                "limit": limit,
                "order": order,
                "nextPageToken": next_page_token,
            },
        ).data

    def get_market_index(
        self,
        index_name: str,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        order: str | None = None,
        next_page_token: str | None = None,
    ) -> Any:
        return self._transport.get(
            f"/price/{_seg(index_name)}/market-index",
            params={
                "from": from_date,
                "to": to_date,
                "limit": limit,
                "order": order,
                "nextPageToken": next_page_token,
            },
        ).data

    def get_instruments(
        self,
        *,
        symbol: str | None = None,
        market_id: str | None = None,
        security_group_id: str | None = None,
        index_name: str | None = None,
        limit: int | None = None,
        page: int | None = None,
    ) -> Any:
        return self._transport.get(
            "/market/instruments",
            params={
                "symbol": symbol,
                "marketId": market_id,
                "securityGroupId": security_group_id,
                "indexName": index_name,
                "limit": limit,
                "page": page,
            },
        ).data

    def get_working_dates(self) -> Any:
        return self._transport.get("/market/working-dates").data

    def get_trading_session(
        self,
        *,
        tsc_prod_grp_id: str | None = None,
        board_id: str | None = None,
    ) -> Any:
        return self._transport.get(
            "/market/trading-session",
            params={"tscProdGrpId": tsc_prod_grp_id, "boardId": board_id},
        ).data

    def get_care_by(self) -> Any:
        """Broker relationship info for the authenticated account."""
        return self._transport.get("/brokers/accounts/care-by").data

    # -- escape hatch -------------------------------------------------------

    def raw(self, method: str, path: str, **kwargs: Any) -> APIResponse:
        """Call any endpoint not covered by a helper (still signed)."""
        return self._transport.request(method, path, **kwargs)
