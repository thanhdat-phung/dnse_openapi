from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from dnse_openapi.auth import AuthClient, FileTokenStore, MemoryTokenStore
from dnse_openapi.errors import TradingTokenRequired
from dnse_openapi.models import OTPType
from dnse_openapi.transport import Transport


def _auth(
    handler: Callable[[httpx.Request], httpx.Response],
    clock: Callable[[], float],
) -> AuthClient:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return AuthClient(
        Transport("test-key", "test-secret", http_client=http_client), clock=clock
    )


def test_create_trading_token_posts_otp_and_caches() -> None:
    requests: list[httpx.Request] = []
    now = [1_000.0]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"tradingToken": "token-1"})

    auth = _auth(handler, lambda: now[0])
    assert not auth.has_valid_token()

    assert auth.create_trading_token("email_otp", "123456") == "token-1"
    assert auth.get_trading_token() == "token-1"
    assert auth.expires_at == 1_000.0 + 8 * 60 * 60

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/registration/trading-token"
    assert json.loads(request.content) == {
        "otpType": "email_otp",
        "passcode": "123456",
    }


def test_trading_token_expires_with_safety_margin() -> None:
    now = [1_000.0]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tradingToken": "token-1"})

    auth = _auth(handler, lambda: now[0])
    auth.create_trading_token(OTPType.EMAIL, "123456")

    now[0] += 8 * 60 * 60 - 120
    assert auth.get_trading_token() == "token-1"

    now[0] += 100  # inside the 60-second safety margin
    with pytest.raises(TradingTokenRequired, match="expired"):
        auth.get_trading_token()
    assert not auth.has_valid_token()


def test_send_email_otp_and_handoff_paths() -> None:
    paths: list[str] = []
    versions: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        versions.append(request.headers["version"])
        if request.url.path.endswith("/smart-otp/handoff"):
            return httpx.Response(200, json={"smartOtp": "654321"})
        return httpx.Response(200, json={})

    auth = _auth(handler, lambda: 0.0)
    auth.send_email_otp()
    assert auth.request_smart_otp() == "654321"
    assert paths == [
        "/registration/send-email-otp",
        "/registration/smart-otp/handoff",
    ]
    # The official SDK pins handoff to 2026-01-01.
    assert versions == ["2026-07-23", "2026-01-01"]


def test_trading_token_accepts_sandbox_hyphenated_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"trading-token": "sandbox-token"})

    auth = _auth(handler, lambda: 0.0)
    assert auth.create_trading_token("smart_otp", "666666") == "sandbox-token"
    assert auth.get_trading_token() == "sandbox-token"


def test_set_trading_token_accepts_external_token() -> None:
    auth = _auth(lambda request: httpx.Response(200, json={}), lambda: 10.0)
    auth.set_trading_token("external", ttl=120)
    assert auth.get_trading_token() == "external"
    assert auth.expires_at == 130.0


def test_memory_store_clear() -> None:
    store = MemoryTokenStore()
    assert store.load() is None
    store.save("t", 123.0)
    assert store.load() == ("t", 123.0)
    store.clear()
    assert store.load() is None


def test_file_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "token.json"
    store = FileTokenStore(path)
    assert store.load() is None

    store.save("token-1", 1234.0)
    assert path.exists()
    assert FileTokenStore(path).load() == ("token-1", 1234.0)

    store.clear()
    assert store.load() is None


def test_file_store_ignores_corrupt_state(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("not json", encoding="utf-8")
    assert FileTokenStore(path).load() is None


def test_missing_trading_token_raises() -> None:
    auth = _auth(lambda request: httpx.Response(200, json={}), lambda: 0.0)
    with pytest.raises(TradingTokenRequired):
        auth.get_trading_token()
