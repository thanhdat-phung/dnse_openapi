from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from dnse_openapi import DNSEClient, Settings
from dnse_openapi.server.app import create_app


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/accounts":
        return httpx.Response(200, json=[{"id": "0001", "dealAccount": True}])
    if path == "/registration/trading-token":
        return httpx.Response(200, json={"tradingToken": "cached-token"})
    if path == "/registration/send-email-otp":
        return httpx.Response(200, json={})
    if path == "/accounts/0001/orders" and request.method == "POST":
        return httpx.Response(200, json={"id": "99", "orderStatus": "PendingNew"})
    if path == "/accounts/0001/orders/511":
        return httpx.Response(200, json={"id": "511"})
    if path == "/accounts/0001/orders/history":
        return httpx.Response(200, json={"orders": [], "totalRecords": 0})
    if path == "/accounts/0001/balances":
        return httpx.Response(200, json={"accountNo": "0001", "cash": 1000})
    if path == "/price/HPG/secdef":
        return httpx.Response(200, json={"symbol": "HPG", "basicPrice": 27.5})
    return httpx.Response(404, json={"status": 404, "code": "NOT_FOUND"})


@pytest.fixture
def server_client(make_client: Callable[..., DNSEClient]) -> DNSEClient:
    return make_client(_handler)


def test_health(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["trading_token_cached"] is False
    assert payload["base_url"] == "https://openapi.dnse.com.vn"


def test_accounts_and_balances(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        assert http.get("/accounts").json()[0]["id"] == "0001"
        assert http.get("/accounts/0001/balances").json()["cash"] == 1000


def test_trading_token_then_order_with_cached_token(
    server_client: DNSEClient,
) -> None:
    with TestClient(create_app(client=server_client)) as http:
        token_response = http.post(
            "/registration/trading-token",
            json={"otpType": "email_otp", "passcode": "123456"},
        )
        assert token_response.status_code == 200
        assert token_response.json() == {"tradingToken": "cached-token"}

        order_response = http.post(
            "/accounts/0001/orders",
            params={"marketType": "STOCK", "orderCategory": "NORMAL"},
            json={
                "symbol": "HPG",
                "side": "NB",
                "orderType": "LO",
                "quantity": 100,
                "price": 27500,
                "loanPackageId": 5757,
            },
        )
    assert order_response.status_code == 200
    assert order_response.json()["id"] == "99"


def test_order_accepts_explicit_trading_token(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.post(
            "/accounts/0001/orders",
            params={"marketType": "STOCK", "orderCategory": "NORMAL"},
            headers={"trading-token": "explicit"},
            json={
                "symbol": "HPG",
                "side": "NB",
                "orderType": "LO",
                "quantity": 100,
                "price": 27500,
                "loanPackageId": 5757,
            },
        )
    assert response.status_code == 200


def test_order_without_token_returns_409(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.post(
            "/accounts/0001/orders",
            params={"marketType": "STOCK", "orderCategory": "NORMAL"},
            json={
                "symbol": "HPG",
                "side": "NB",
                "orderType": "LO",
                "quantity": 100,
                "price": 27500,
                "loanPackageId": 5757,
            },
        )
    assert response.status_code == 409
    assert response.json()["status"] == "error"


def test_invalid_stop_order_returns_422(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.post(
            "/accounts/0001/orders",
            params={"marketType": "STOCK", "orderCategory": "STOP"},
            headers={"trading-token": "tok"},
            json={
                "symbol": "HPG",
                "side": "NB",
                "quantity": 100,
                "price": 27500,
                "loanPackageId": 5757,
            },
        )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_history_route_is_not_shadowed_by_order_id(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.get(
            "/accounts/0001/orders/history",
            params={"marketType": "STOCK", "pageIndex": 0, "pageSize": 10},
        )
    assert response.status_code == 200
    assert response.json()["totalRecords"] == 0


def test_replace_and_cancel_paths(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        replaced = http.put(
            "/accounts/0001/orders/511",
            params={"marketType": "STOCK", "orderCategory": "NORMAL"},
            headers={"trading-token": "tok"},
            json={"price": 12500, "quantity": 100},
        )
        canceled = http.delete(
            "/accounts/0001/orders/511",
            params={"marketType": "STOCK", "orderCategory": "NORMAL"},
            headers={"trading-token": "tok"},
        )
    assert replaced.status_code == 200
    assert canceled.status_code == 200


def test_local_server_token_is_enforced(server_client: DNSEClient) -> None:
    settings = Settings(api_key="k", api_secret="s", server_token="local-secret")
    with TestClient(create_app(client=server_client, settings=settings)) as http:
        assert http.get("/accounts").status_code == 401
        assert (
            http.get("/accounts", headers={"X-Local-Token": "local-secret"}).status_code
            == 200
        )
        assert (
            http.get(
                "/accounts", headers={"Authorization": "Bearer local-secret"}
            ).status_code
            == 200
        )


def test_market_data_passthrough(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.get("/price/HPG/secdef", params={"boardId": "G1"})
    assert response.status_code == 200
    assert response.json()["basicPrice"] == 27.5


def test_upstream_error_is_mapped(server_client: DNSEClient) -> None:
    with TestClient(create_app(client=server_client)) as http:
        response = http.get("/accounts/0001/positions")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
