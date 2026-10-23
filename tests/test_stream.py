from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from dnse_openapi.config import (
    DEFAULT_WS_URL,
    SANDBOX_WS_URL,
    Settings,
    ws_url_for,
)
from dnse_openapi.errors import DNSEStreamError, DNSEValidationError
from dnse_openapi.stream import (
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

WELCOME = {"action": "welcome", "session_id": "conn_1"}


class FakeConnection:
    """Minimal stand-in for a websockets connection."""

    def __init__(self, script: list[Any], *, auto_auth: bool = True) -> None:
        self._script = deque(script)
        self._auto_auth = auto_auth
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def recv(self) -> Any:
        while self._script:
            item = self._script.popleft()
            if callable(item):
                return item()
            if isinstance(item, (dict, list)):
                return json.dumps(item)
            return item
        await asyncio.Event().wait()  # block until cancelled
        raise AssertionError("unreachable")

    async def send(self, raw: Any) -> None:
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload["action"] == "auth" and self._auto_auth:
            self._script.appendleft({"action": "auth_success"})
        elif payload["action"] == "subscribe":
            self._script.appendleft(
                {
                    "action": "subscribed",
                    "channel": payload["channels"][0]["name"],
                }
            )

    async def close(self) -> None:
        self.closed = True


def make_factory(
    scripts: list[list[Any]], *, auto_auth: bool = True
) -> tuple[Callable[..., Awaitable[FakeConnection]], list[FakeConnection]]:
    connections: list[FakeConnection] = []
    pending = deque(scripts)

    async def connect(url: str, **kwargs: Any) -> FakeConnection:
        script = pending.popleft() if pending else [WELCOME]
        connection = FakeConnection(script, auto_auth=auto_auth)
        connections.append(connection)
        return connection

    return connect, connections


def test_auth_payload_signature_is_hex_hmac_sha256() -> None:
    payload = auth_payload("key", "secret", timestamp=1750000000, nonce="1750000000123456")
    expected = hmac.new(
        b"secret",
        b"key:1750000000:1750000000123456",
        hashlib.sha256,
    ).hexdigest()
    assert payload == {
        "action": "auth",
        "api_key": "key",
        "signature": expected,
        "timestamp": 1750000000,
        "nonce": "1750000000123456",
    }


def test_auth_payload_generates_fresh_nonce() -> None:
    first = auth_payload("key", "secret")
    second = auth_payload("key", "secret")
    assert first["nonce"] != second["nonce"]
    assert first["signature"] != second["signature"]


def test_channel_names() -> None:
    assert tick_channel("G1") == "tick.G1.json"
    assert tick_extra_channel("G1") == "tick_extra.G1.json"
    assert top_price_channel("G1") == "top_price.G1.json"
    assert expected_price_channel("G1") == "expected_price.G1.json"
    assert security_definition_channel("G1") == "security_definition.G1.json"
    assert ohlc_channel("1D") == "ohlc.1D.json"
    assert ohlc_channel("15", closed=True) == "ohlc_closed.15.json"
    assert market_index_channel("VNINDEX") == "market_index.VNINDEX.json"
    assert estimated_market_index_channel("VN30") == "estimated_market_index.VN30.json"
    assert foreign_channel("G1") == "foreign.G1.json"
    assert session_channel("STO", "G1") == "session.STO.G1.json"
    assert tick_channel("G1", encoding="msgpack") == "tick.G1.msgpack"


def test_channel_rejects_unknown_encoding() -> None:
    with pytest.raises(DNSEValidationError):
        tick_channel("G1", encoding="csv")


def test_ws_url_follows_base_url() -> None:
    assert ws_url_for("https://openapi.dnse.com.vn") == DEFAULT_WS_URL
    assert ws_url_for("https://sb-openapi.dnse.com.vn") == SANDBOX_WS_URL
    assert ws_url_for("https://example.test") == DEFAULT_WS_URL


def test_settings_derives_and_overrides_ws_url() -> None:
    sandbox = Settings(api_key="k", api_secret="s", base_url="https://sb-openapi.dnse.com.vn")
    assert sandbox.ws_url == SANDBOX_WS_URL

    custom = Settings(
        api_key="k",
        api_secret="s",
        base_url="https://sb-openapi.dnse.com.vn",
        ws_url="wss://proxy.internal/stream",
    )
    assert custom.ws_url == "wss://proxy.internal/stream"

    with pytest.raises(ValueError):
        Settings(api_key="k", api_secret="s", ws_url="https://not-a-websocket")


def test_stream_authenticates_subscribes_and_answers_ping() -> None:
    connect, connections = make_factory(
        [
            [
                WELCOME,
                {"action": "ping", "timestamp": 123},
                {"T": "tick", "symbol": "HPG", "matchPrice": 27.5},
                {"T": "tick", "symbol": "HPG", "matchPrice": 27.6},
            ]
        ]
    )
    controls: list[dict[str, Any]] = []

    async def scenario() -> list[dict[str, Any]]:
        stream = MarketStream(
            "key",
            "secret",
            heartbeat_interval=None,
            connect=connect,
            on_control=controls.append,
        )
        received: list[dict[str, Any]] = []
        async with stream:
            await stream.subscribe(tick_channel("G1"), ["hpg"])
            async for message in stream.messages():
                received.append(message)
                if len(received) == 2:
                    break
        assert stream.connected is False
        return received

    received = asyncio.run(scenario())

    assert [message["matchPrice"] for message in received] == [27.5, 27.6]
    first = connections[0]
    assert first.sent[0]["action"] == "auth"
    assert first.sent[1] == {
        "action": "subscribe",
        "channels": [{"name": "tick.G1.json", "symbols": ["HPG"]}],
    }
    assert {"action": "pong", "timestamp": 123} in first.sent
    assert controls == [
        {"action": "subscribed", "channel": "tick.G1.json"},
    ]
    assert first.closed is True


def test_stream_raises_without_auto_reconnect() -> None:
    def boom() -> Any:
        raise OSError("socket closed")

    connect, _ = make_factory([[WELCOME, boom]])

    async def scenario() -> None:
        stream = MarketStream(
            "key", "secret", heartbeat_interval=None, auto_reconnect=False, connect=connect
        )
        async with stream:
            async for _ in stream.messages():
                pass

    with pytest.raises(DNSEStreamError):
        asyncio.run(scenario())


def test_stream_reconnects_and_resubscribes() -> None:
    def boom() -> Any:
        raise OSError("socket closed")

    connect, connections = make_factory(
        [
            [WELCOME, boom],
            [WELCOME, {"T": "tick", "symbol": "HPG", "matchPrice": 27.7}],
        ]
    )

    async def no_sleep(_: float) -> None:
        return None

    async def scenario() -> dict[str, Any]:
        stream = MarketStream(
            "key",
            "secret",
            heartbeat_interval=None,
            connect=connect,
            sleep=no_sleep,
        )
        async with stream:
            await stream.subscribe(tick_channel("G1"), ["HPG"])
            async for message in stream.messages():
                return message
        raise AssertionError("unreachable")

    message = asyncio.run(scenario())

    assert message["matchPrice"] == 27.7
    assert len(connections) == 2
    assert [entry["action"] for entry in connections[1].sent] == ["auth", "subscribe"]
    assert connections[1].sent[1]["channels"][0]["symbols"] == ["HPG"]


def test_stream_surfaces_server_errors() -> None:
    connect, _ = make_factory([[WELCOME, {"action": "error", "code": "X", "message": "bad"}]])

    async def scenario() -> None:
        stream = MarketStream("key", "secret", heartbeat_interval=None, connect=connect)
        async with stream:
            async for _ in stream.messages():
                pass

    with pytest.raises(DNSEStreamError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.code == "X"


def test_auth_failure_is_raised() -> None:
    connect, _ = make_factory(
        [[WELCOME, {"action": "error", "code": "AUTH_FAILED", "message": "nope"}]],
        auto_auth=False,
    )

    async def scenario() -> None:
        async with MarketStream("key", "secret", heartbeat_interval=None, connect=connect):
            pass

    with pytest.raises(DNSEStreamError) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.code == "AUTH_FAILED"


def test_data_message_with_action_and_T_is_not_treated_as_control() -> None:
    connect, _ = make_factory(
        [[WELCOME, {"action": "estimated_market_index", "T": "e", "symbol": "VN30"}]]
    )

    async def scenario() -> dict[str, Any]:
        stream = MarketStream("key", "secret", heartbeat_interval=None, connect=connect)
        async with stream:
            async for message in stream.messages():
                return message
        raise AssertionError("unreachable")

    assert asyncio.run(scenario())["symbol"] == "VN30"
