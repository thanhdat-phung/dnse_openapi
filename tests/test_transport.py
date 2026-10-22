from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest

from dnse_openapi import (
    DNSEClient,
    DNSEClientError,
    DNSERateLimitError,
    DNSEServerError,
    DNSETransportError,
    QuotaExceededError,
)
from dnse_openapi.config import DEFAULT_API_VERSION
from dnse_openapi.models import MarketType
from dnse_openapi.signing import build_signing_string, sign


def _nonce(header: str) -> str:
    match = re.search(r'nonce="([0-9a-f]{32})"', header)
    assert match, header
    return match.group(1)


def _assert_signature(request: httpx.Request, path: str) -> None:
    header = request.headers["X-Signature"]
    assert 'algorithm="hmac-sha256"' in header
    assert 'headers="(request-target) date"' in header
    expected = sign(
        "test-secret",
        build_signing_string("GET", path, request.headers["Date"], _nonce(header)),
    )
    assert f'signature="{expected}"' in header


def test_request_is_signed_and_versioned(make_client: Callable[..., DNSEClient]) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=[{"id": "0001"}])

    client = make_client(handler)
    assert client.accounts.get_accounts() == [{"id": "0001"}]

    request = captured["request"]
    assert request.method == "GET"
    assert request.url.path == "/accounts"
    assert request.headers["x-api-key"] == "test-key"
    assert request.headers["version"] == DEFAULT_API_VERSION
    _assert_signature(request, "/accounts")


def test_query_parameters_are_not_part_of_the_signature(
    make_client: Callable[..., DNSEClient],
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"orders": []})

    client = make_client(handler)
    client.accounts.get_orders(
        "0001", MarketType.STOCK, page_index=2, page_size=5
    )

    request = captured["request"]
    assert request.url.params["marketType"] == "STOCK"
    assert request.url.params["pageIndex"] == "2"
    assert request.url.params["pageSize"] == "5"
    _assert_signature(request, "/accounts/0001/orders")


def test_retry_on_429_uses_a_fresh_signature(
    make_client: Callable[..., DNSEClient],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[])

    client = make_client(handler, max_retries=2, sleep=lambda _: None)
    assert client.accounts.get_accounts() == []

    assert len(requests) == 2
    first_nonce = _nonce(requests[0].headers["X-Signature"])
    second_nonce = _nonce(requests[1].headers["X-Signature"])
    assert first_nonce != second_nonce


def test_idempotent_retry_on_5xx(make_client: Callable[..., DNSEClient]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"status": 503})
        return httpx.Response(200, json={})

    client = make_client(handler, max_retries=1, sleep=lambda _: None)
    client.accounts.get_accounts()
    assert len(requests) == 2


def test_post_is_not_retried_on_5xx(make_client: Callable[..., DNSEClient]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, json={"status": 500, "code": "OA-009"})

    client = make_client(handler, max_retries=3, sleep=lambda _: None)
    with pytest.raises(DNSEServerError):
        client.auth.send_email_otp()
    assert len(requests) == 1


def test_post_is_retried_on_429(make_client: Callable[..., DNSEClient]) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={})

    client = make_client(handler, max_retries=1, sleep=lambda _: None)
    client.auth.send_email_otp()
    assert len(requests) == 2


def test_client_error_carries_dnse_code(make_client: Callable[..., DNSEClient]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "status": 400,
                "code": "OA-100",
                "message": "Invalid input: otpType is not registered",
            },
        )

    client = make_client(handler, max_retries=0)
    with pytest.raises(DNSEClientError) as info:
        client.accounts.get_accounts()
    assert info.value.status == 400
    assert info.value.code == "OA-100"
    assert "OA-100" in str(info.value)


def test_daily_quota_is_distinguished_from_generic_forbidden(
    make_client: Callable[..., DNSEClient],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"status": "error", "code": "OA-401", "message": "Quota exceeded"}
        )

    client = make_client(handler, max_retries=0)
    with pytest.raises(QuotaExceededError) as info:
        client.accounts.get_accounts()
    assert info.value.status == 403
    assert info.value.code == "OA-401"


def test_rate_limit_exhausted_raises(make_client: Callable[..., DNSEClient]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    client = make_client(handler, max_retries=0)
    with pytest.raises(DNSERateLimitError):
        client.accounts.get_accounts()


def test_network_error_is_wrapped(make_client: Callable[..., DNSEClient]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = make_client(handler, max_retries=0)
    with pytest.raises(DNSETransportError, match="boom"):
        client.accounts.get_accounts()


def test_custom_headers_cannot_override_signing_headers(
    make_client: Callable[..., DNSEClient],
) -> None:
    client = make_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="managed by the transport"):
        client.transport.get("/accounts", headers={"x-api-key": "other"})
