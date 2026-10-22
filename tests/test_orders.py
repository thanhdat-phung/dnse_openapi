from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import ValidationError

from dnse_openapi import (
    DNSEClient,
    DNSEValidationError,
    NormalOrder,
    OCOOrder,
    StopOrder,
    TradingTokenRequired,
)
from dnse_openapi.models import MarketType


def _normal() -> NormalOrder:
    return NormalOrder(
        symbol="HPG",
        side="NB",
        order_type="LO",
        quantity=100,
        price=27500,
        loan_package_id=5757,
    )


def test_place_normal_order(make_client: Callable[..., DNSEClient]) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "1631", "orderStatus": "PendingNew"})

    client = make_client(handler)
    result = client.orders.place_order(
        "0001179019", MarketType.STOCK, _normal(), trading_token="trading-token"
    )
    assert result["id"] == "1631"

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path == "/accounts/0001179019/orders"
    assert request.url.params["marketType"] == "STOCK"
    assert request.url.params["orderCategory"] == "NORMAL"
    assert request.headers["trading-token"] == "trading-token"
    assert json.loads(request.content) == {
        "symbol": "HPG",
        "side": "NB",
        "orderType": "LO",
        "quantity": 100,
        "price": 27500,
        "loanPackageId": 5757,
    }


def test_place_stop_order(make_client: Callable[..., DNSEClient]) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"id": "stop-1"})

    client = make_client(handler)
    order = StopOrder(
        symbol="41I1G8000",
        side="NS",
        quantity=3,
        price=1900,
        loan_package_id=2278,
        stop_price=1700,
        condition_operator="<=",
        duration_date_time=datetime(
            2026, 8, 20, 7, 30, tzinfo=timezone(timedelta(hours=7))
        ),
    )
    client.orders.place_order(
        "0001179019", MarketType.DERIVATIVE, order, trading_token="tok"
    )

    request = captured["request"]
    assert request.url.params["orderCategory"] == "STOP"
    assert request.url.params["marketType"] == "DERIVATIVE"
    body = json.loads(request.content)
    assert body["stopPrice"] == 1700
    assert body["conditionOperator"] == "<="
    assert body["durationType"] == "GTD"
    assert body["durationDateTime"] == "2026-08-20T07:30:00.000+07:00"


def test_oco_order_rejected_for_stock(make_client: Callable[..., DNSEClient]) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    order = OCOOrder(
        symbol="41I1G8000",
        side="NB",
        quantity=3,
        price=1990,
        loan_package_id=2278,
        stop_price=2000,
        stop_order_price=2005,
    )
    with pytest.raises(DNSEValidationError, match="DERIVATIVE"):
        client.orders.place_order("0001", MarketType.STOCK, order, trading_token="tok")
    assert calls == []


def test_stop_order_rejected_for_bond(make_client: Callable[..., DNSEClient]) -> None:
    client = make_client(lambda request: httpx.Response(200, json={}))
    order = StopOrder(
        symbol="HPG",
        side="NS",
        quantity=100,
        price=27500,
        loan_package_id=5757,
        stop_price=27000,
        condition_operator="<=",
        duration_date_time=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    with pytest.raises(DNSEValidationError, match="BOND"):
        client.orders.place_order("0001", MarketType.BOND, order, trading_token="tok")


def test_place_raw_validates_against_category(
    make_client: Callable[..., DNSEClient],
) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"id": "1"}))
    with pytest.raises(ValidationError):
        client.orders.place_raw(
            "0001",
            "STOCK",
            "STOP",
            {"symbol": "HPG", "side": "NB", "quantity": 100, "price": 27500},
            trading_token="tok",
        )


def test_replace_order_uses_put(make_client: Callable[..., DNSEClient]) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": 1626})

    client = make_client(handler)
    client.orders.replace_order(
        "0001",
        "511",
        "STOCK",
        {"price": 12500, "quantity": 100},
        trading_token="tok",
    )
    request = captured["request"]
    assert request.method == "PUT"
    assert request.url.path == "/accounts/0001/orders/511"
    assert json.loads(request.content) == {"price": 12500, "quantity": 100}


def test_derivative_replace_accepts_only_one_field(
    make_client: Callable[..., DNSEClient],
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    with pytest.raises(DNSEValidationError, match="one of price or quantity"):
        client.orders.replace_order(
            "0001",
            "511",
            "DERIVATIVE",
            {"price": 1900, "quantity": 3},
            trading_token="tok",
        )
    assert calls == []


def test_cancel_order_uses_delete(make_client: Callable[..., DNSEClient]) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "511"})

    client = make_client(handler)
    client.orders.cancel_order("0001", "511", "STOCK", trading_token="tok")
    request = captured["request"]
    assert request.method == "DELETE"
    assert request.url.params["orderCategory"] == "NORMAL"
    assert request.headers["trading-token"] == "tok"


def test_mutations_require_a_trading_token(
    make_client: Callable[..., DNSEClient],
) -> None:
    client = make_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(TradingTokenRequired):
        client.orders.place_order("0001", "STOCK", _normal())


def test_client_place_order_uses_default_account(
    make_client: Callable[..., DNSEClient],
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"id": "1"})

    client = make_client(handler, account_no="0001179019")
    client.place_order(_normal(), trading_token="tok")
    assert captured["request"].url.path == "/accounts/0001179019/orders"


def test_client_place_order_requires_account(
    make_client: Callable[..., DNSEClient],
) -> None:
    client = make_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(DNSEValidationError, match="account_no"):
        client.place_order(_normal(), trading_token="tok")


def test_close_and_reverse_position(make_client: Callable[..., DNSEClient]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.orders.close_position("pos-1", "DERIVATIVE", trading_token="tok")
    client.orders.reverse_position("pos-2", trading_token="tok")

    assert requests[0].url.path == "/positions/pos-1/close"
    assert requests[0].url.params["marketType"] == "DERIVATIVE"
    assert requests[0].headers["version"] == "2026-07-23"
    assert requests[1].url.path == "/positions/pos-2/reverse"
    assert requests[1].url.params["marketType"] == "DERIVATIVE"
    # The official SDK pins reverse-position to 2026-01-01.
    assert requests[1].headers["version"] == "2026-01-01"
