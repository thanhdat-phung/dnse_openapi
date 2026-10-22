"""Local FastAPI facade for the DNSE OpenAPI.

The routes mirror DNSE's paths and query parameters, so examples from the
official docs can be pointed at ``http://127.0.0.1:8000`` unchanged. The server
adds credentials and, when available, the cached trading token.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .._version import __version__
from ..client import DNSEClient
from ..config import Settings
from ..errors import (
    DNSEAPIError,
    DNSEError,
    DNSEValidationError,
    TradingTokenRequired,
)
from ..models import MarketType, OrderCategory, TradingTokenRequest

__all__ = ["create_app"]


def _local_token_dependency(
    request: Request,
    x_local_token: str | None = Header(default=None, alias="X-Local-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    expected: str | None = getattr(request.app.state, "server_token", None)
    if not expected:
        return
    supplied = x_local_token
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid local server token")


def _client(request: Request) -> DNSEClient:
    client: DNSEClient = request.app.state.client
    return client


def _trading_token(
    request: Request,
    header_token: str | None = Header(default=None, alias="trading-token"),
) -> str:
    if header_token:
        return header_token
    try:
        return _client(request).auth.get_trading_token()
    except TradingTokenRequired as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "no valid trading token; POST /registration/trading-token "
                "or send a trading-token header"
            ),
        ) from exc


def _build_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(_local_token_dependency)])

    # -- health -------------------------------------------------------------

    @router.get("/health", tags=["system"])
    def health(request: Request) -> dict[str, Any]:
        client = _client(request)
        return {
            "status": "ok",
            "version": __version__,
            "base_url": client.transport.base_url,
            "api_version": client.transport.api_version,
            "trading_token_cached": client.auth.has_valid_token(),
        }

    # -- accounts -----------------------------------------------------------

    @router.get("/accounts", tags=["accounts"])
    def get_accounts(request: Request) -> Any:
        return _client(request).accounts.get_accounts()

    @router.get("/accounts/{account_no}/balances", tags=["accounts"])
    def get_balances(account_no: str, request: Request) -> Any:
        return _client(request).accounts.get_balances(account_no)

    @router.get("/accounts/{account_no}/loan-packages", tags=["accounts"])
    def get_loan_packages(
        account_no: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        symbol: str | None = Query(default=None),
    ) -> Any:
        return _client(request).accounts.get_loan_packages(
            account_no, market_type, symbol
        )

    @router.get("/accounts/{account_no}/ppse", tags=["accounts"])
    def get_ppse(
        account_no: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        symbol: str = Query(...),
        price: float = Query(...),
        loan_package_id: int = Query(..., alias="loanPackageId"),
    ) -> Any:
        return _client(request).accounts.get_ppse(
            account_no, symbol, price, loan_package_id, market_type
        )

    @router.get("/accounts/{account_no}/positions", tags=["positions"])
    def get_positions(
        account_no: str,
        request: Request,
        market_type: MarketType = Query(
            default=MarketType.STOCK, alias="marketType"
        ),
    ) -> Any:
        return _client(request).accounts.get_positions(account_no, market_type)

    @router.get("/positions/{position_id}", tags=["positions"])
    def get_position(
        position_id: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
    ) -> Any:
        return _client(request).accounts.get_position(position_id, market_type)

    # -- orders -------------------------------------------------------------

    @router.get("/accounts/{account_no}/orders", tags=["orders"])
    def get_orders(
        account_no: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        order_category: OrderCategory = Query(
            default=OrderCategory.NORMAL, alias="orderCategory"
        ),
        page_index: int = Query(default=0, ge=0, alias="pageIndex"),
        page_size: int = Query(default=10, ge=1, le=1000, alias="pageSize"),
    ) -> Any:
        return _client(request).accounts.get_orders(
            account_no,
            market_type,
            order_category,
            page_index=page_index,
            page_size=page_size,
        )

    @router.get("/accounts/{account_no}/orders/history", tags=["orders"])
    def get_order_history(
        account_no: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        from_date: str | None = Query(default=None, alias="from"),
        to_date: str | None = Query(default=None, alias="to"),
        page_index: int | None = Query(default=None, alias="pageIndex"),
        page_size: int | None = Query(default=None, alias="pageSize"),
    ) -> Any:
        return _client(request).accounts.get_order_history(
            account_no,
            market_type,
            from_date=from_date,
            to_date=to_date,
            page_index=page_index,
            page_size=page_size,
        )

    @router.get("/accounts/{account_no}/orders/{order_id}", tags=["orders"])
    def get_order_detail(
        account_no: str,
        order_id: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        order_category: OrderCategory | None = Query(
            default=None, alias="orderCategory"
        ),
    ) -> Any:
        return _client(request).accounts.get_order_detail(
            account_no, order_id, market_type, order_category
        )

    @router.post("/accounts/{account_no}/orders", tags=["orders"])
    def place_order(
        account_no: str,
        request: Request,
        payload: dict[str, Any] = Body(...),
        market_type: MarketType = Query(..., alias="marketType"),
        order_category: OrderCategory = Query(
            default=OrderCategory.NORMAL, alias="orderCategory"
        ),
        trading_token: str = Depends(_trading_token),
    ) -> Any:
        return _client(request).orders.place_raw(
            account_no,
            market_type,
            order_category,
            payload,
            trading_token=trading_token,
        )

    @router.put("/accounts/{account_no}/orders/{order_id}", tags=["orders"])
    def replace_order(
        account_no: str,
        order_id: str,
        request: Request,
        payload: dict[str, Any] = Body(...),
        market_type: MarketType = Query(..., alias="marketType"),
        order_category: OrderCategory = Query(
            default=OrderCategory.NORMAL, alias="orderCategory"
        ),
        trading_token: str = Depends(_trading_token),
    ) -> Any:
        return _client(request).orders.replace_order(
            account_no,
            order_id,
            market_type,
            payload,
            order_category=order_category,
            trading_token=trading_token,
        )

    @router.delete("/accounts/{account_no}/orders/{order_id}", tags=["orders"])
    def cancel_order(
        account_no: str,
        order_id: str,
        request: Request,
        market_type: MarketType = Query(..., alias="marketType"),
        order_category: OrderCategory = Query(
            default=OrderCategory.NORMAL, alias="orderCategory"
        ),
        trading_token: str = Depends(_trading_token),
    ) -> Any:
        return _client(request).orders.cancel_order(
            account_no,
            order_id,
            market_type,
            order_category=order_category,
            trading_token=trading_token,
        )

    # -- 2FA ----------------------------------------------------------------

    @router.post("/registration/send-email-otp", tags=["auth"])
    def send_email_otp(request: Request) -> Any:
        return _client(request).auth.send_email_otp().data

    @router.post("/registration/smart-otp/handoff", tags=["auth"])
    def smart_otp_handoff(request: Request) -> Any:
        return _client(request).auth.create_smart_otp_handoff().data

    @router.post("/registration/trading-token", tags=["auth"])
    def create_trading_token(
        request: Request, body: TradingTokenRequest
    ) -> dict[str, str]:
        token = _client(request).auth.create_trading_token(
            body.otp_type, body.passcode
        )
        return {"tradingToken": token}

    # -- positions actions --------------------------------------------------

    @router.post("/positions/{position_id}/close", tags=["positions"])
    def close_position(
        position_id: str,
        request: Request,
        market_type: MarketType = Query(
            default=MarketType.DERIVATIVE, alias="marketType"
        ),
        trading_token: str = Depends(_trading_token),
    ) -> Any:
        return _client(request).orders.close_position(
            position_id, market_type, trading_token=trading_token
        )

    @router.post("/positions/{position_id}/reverse", tags=["positions"])
    def reverse_position(
        position_id: str,
        request: Request,
        trading_token: str = Depends(_trading_token),
    ) -> Any:
        return _client(request).orders.reverse_position(
            position_id, trading_token=trading_token
        )

    # -- a little market data ----------------------------------------------

    @router.get("/price/{symbol}/secdef", tags=["market-data"])
    def get_security_definition(
        symbol: str,
        request: Request,
        board_id: str | None = Query(default=None, alias="boardId"),
    ) -> Any:
        return _client(request).accounts.get_security_definition(symbol, board_id)

    @router.get("/price/{symbol}/trades/latest", tags=["market-data"])
    def get_latest_trade(
        symbol: str,
        request: Request,
        board_id: str | None = Query(default=None, alias="boardId"),
    ) -> Any:
        return _client(request).accounts.get_latest_trade(symbol, board_id)

    @router.get("/price/{symbol}/quotes/latest", tags=["market-data"])
    def get_latest_quote(
        symbol: str,
        request: Request,
        board_id: str | None = Query(default=None, alias="boardId"),
    ) -> Any:
        return _client(request).accounts.get_latest_quote(symbol, board_id)

    return router


def create_app(
    client: DNSEClient | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Create the local server.

    ``client`` is injectable for tests; otherwise it is built from environment
    variables. When this function builds the client it also closes it on
    shutdown.
    """
    owns_client = client is None
    if client is None:
        settings = settings or Settings.from_env()
        client = DNSEClient.from_settings(settings)
    server_token = settings.server_token if settings else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_client:
            client.close()

    app = FastAPI(
        title="DNSE OpenAPI Local Server",
        description=(
            "Local, authenticated facade over the DNSE OpenAPI. Routes mirror "
            "DNSE paths; credentials never leave this process."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.state.client = client
    app.state.server_token = server_token
    app.include_router(_build_router())

    @app.exception_handler(DNSEError)
    async def handle_dnse_error(request: Request, exc: DNSEError) -> JSONResponse:
        if isinstance(exc, TradingTokenRequired):
            status = 409
        elif isinstance(exc, DNSEValidationError):
            status = 422
        elif isinstance(exc, DNSEAPIError):
            status = exc.status or 502
        else:
            status = 500
        code = getattr(exc, "code", None) or type(exc).__name__
        return JSONResponse(
            status_code=status,
            content={"status": "error", "code": code, "message": str(exc)},
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "code": "VALIDATION_ERROR",
                "message": "invalid order payload",
                "details": jsonable_encoder(
                    exc.errors(include_url=False, include_context=False)
                ),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
            },
        )

    return app
