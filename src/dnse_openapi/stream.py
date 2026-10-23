"""DNSE market-data WebSocket client.

DNSE publishes market data over a WebSocket at ``/v1/stream``. The protocol is
application-level JSON (or msgpack):

1. the server sends ``{"action": "welcome"}``;
2. the client sends ``{"action": "auth", ...}`` signed with
   ``HMAC-SHA256(api_secret, f"{api_key}:{timestamp}:{nonce}").hexdigest()``;
3. the client subscribes to channels such as ``tick.G1.json``;
4. the server pushes data messages, identified by their ``T`` field, and
   ``ping`` keepalives that must be answered with ``pong``.

:class:`MarketStream` performs steps 1-3, answers keepalives and reconnects
with the full handshake when the server drops the connection (the server closes
after 8 hours, and after a missed heartbeat).

This module never imports :mod:`websockets` at module level, so the core
package still installs with only ``httpx`` and ``pydantic``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

from .config import DEFAULT_WS_URL, Settings, ws_url_for
from .errors import DNSEStreamError, DNSEValidationError

_LOGGER = logging.getLogger(__name__)

ENCODINGS = ("json", "msgpack")
"""Wire encodings accepted by the stream endpoint."""

CONTROL_ACTIONS = frozenset(
    {
        "welcome",
        "auth_success",
        "subscribed",
        "unsubscribed",
        "ping",
        "pong",
        "connection_expired",
        "error",
    }
)
"""Control actions; anything else (or any message with ``T``) is market data."""

STREAM_PATH = "/v1/stream"


# -- channel names ---------------------------------------------------------


def _check_encoding(encoding: str) -> str:
    if encoding not in ENCODINGS:
        raise DNSEValidationError(
            f"encoding must be one of {', '.join(ENCODINGS)}, not {encoding!r}"
        )
    return encoding


def tick_channel(board_id: str, *, encoding: str = "json") -> str:
    """Matched trades for one board (``tick.G1.json``)."""
    return f"tick.{board_id}.{_check_encoding(encoding)}"


def tick_extra_channel(board_id: str, *, encoding: str = "json") -> str:
    """Matched trades with aggressor side and average price."""
    return f"tick_extra.{board_id}.{_check_encoding(encoding)}"


def top_price_channel(board_id: str, *, encoding: str = "json") -> str:
    """Order-book depth (``top_price.G1.json``)."""
    return f"top_price.{board_id}.{_check_encoding(encoding)}"


def expected_price_channel(board_id: str, *, encoding: str = "json") -> str:
    """ATO/ATC expected match price and quantity."""
    return f"expected_price.{board_id}.{_check_encoding(encoding)}"


def security_definition_channel(board_id: str, *, encoding: str = "json") -> str:
    """Reference, ceiling and floor prices, sent around 08:00 daily."""
    return f"security_definition.{board_id}.{_check_encoding(encoding)}"


def ohlc_channel(
    resolution: str, *, closed: bool = False, encoding: str = "json"
) -> str:
    """Forming candles (``ohlc``) or finished candles (``ohlc_closed``)."""
    prefix = "ohlc_closed" if closed else "ohlc"
    return f"{prefix}.{resolution}.{_check_encoding(encoding)}"


def market_index_channel(index_name: str, *, encoding: str = "json") -> str:
    """Index snapshots such as ``market_index.VNINDEX.json``."""
    return f"market_index.{index_name}.{_check_encoding(encoding)}"


def estimated_market_index_channel(index_name: str, *, encoding: str = "json") -> str:
    """Estimated index (``estimated_market_index.VN30.json``)."""
    return f"estimated_market_index.{index_name}.{_check_encoding(encoding)}"


def foreign_channel(board_id: str, *, encoding: str = "json") -> str:
    """Foreign-investor trading per symbol."""
    return f"foreign.{board_id}.{_check_encoding(encoding)}"


def session_channel(
    product_group_id: str, board_id: str, *, encoding: str = "json"
) -> str:
    """Trading-session state (``session.STO.G1.json``)."""
    return f"session.{product_group_id}.{board_id}.{_check_encoding(encoding)}"


# -- authentication --------------------------------------------------------


def auth_payload(
    api_key: str,
    api_secret: str,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build the ``auth`` message.

    ``timestamp`` is in seconds and must stay within five minutes of DNSE's
    clock. ``nonce`` is a microsecond timestamp and must be fresh for every
    attempt, including reconnects.
    """
    if timestamp is None:
        timestamp = int(time.time())
    if nonce is None:
        nonce = _fresh_nonce()
    message = f"{api_key}:{timestamp}:{nonce}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "action": "auth",
        "api_key": api_key,
        "signature": signature,
        "timestamp": timestamp,
        "nonce": nonce,
    }


_LAST_NONCE = 0


def _fresh_nonce() -> str:
    """Microsecond timestamp that is unique even if the clock stalls."""
    global _LAST_NONCE
    value = int(time.time() * 1_000_000)
    if value <= _LAST_NONCE:
        value = _LAST_NONCE + 1
    _LAST_NONCE = value
    return str(value)


# -- stream ----------------------------------------------------------------


class MarketStream:
    """Authenticated market-data stream with keepalive and reconnect.

    Typical use::

        async with client.market_stream() as stream:
            await stream.subscribe(tick_channel("G1"), ["HPG"])
            async for message in stream.messages():
                print(message["symbol"], message.get("matchPrice"))

    ``messages()`` yields data only. Control frames (``subscribed``, ``error``,
    ``connection_expired``, ...) are handled internally; pass ``on_control`` if
    you want to observe them, for example to wait for a subscription ack.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        url: str = DEFAULT_WS_URL,
        encoding: str = "json",
        heartbeat_interval: float | None = 25.0,
        auto_reconnect: bool = True,
        max_backoff: float = 60.0,
        open_timeout: float = 10.0,
        on_control: Callable[[Mapping[str, Any]], None] | None = None,
        connect: Callable[..., Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key or not api_secret:
            raise DNSEValidationError("api_key and api_secret are required")
        if not url.startswith(("wss://", "ws://")):
            raise DNSEValidationError("url must start with wss:// or ws://")
        self._api_key = api_key
        self._api_secret = api_secret
        self._url = url.rstrip("/") + STREAM_PATH
        self._encoding = _check_encoding(encoding)
        self._heartbeat_interval = heartbeat_interval
        self._auto_reconnect = auto_reconnect
        self._max_backoff = max_backoff
        self._open_timeout = open_timeout
        self._on_control = on_control
        self._connect_factory = connect
        self._sleep = sleep

        self._ws: Any = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._closed_errors: tuple[type[BaseException], ...] = ()
        self._connection_closed: type[BaseException] = ConnectionError
        self._subscriptions: dict[str, list[str]] = {}
        self._packer: Any = None

    # -- construction ------------------------------------------------------

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> MarketStream:
        """Build a stream from :class:`dnse_openapi.Settings`."""
        return cls(
            settings.api_key,
            settings.api_secret,
            url=settings.ws_url or ws_url_for(settings.base_url),
            **overrides,
        )

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> MarketStream:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the socket, authenticate and restore existing subscriptions."""
        if self._ws is not None:
            return
        await self._open()

    async def close(self) -> None:
        """Close the socket. The stream can be connected again afterwards."""
        await self._teardown()
        self._subscriptions.clear()

    async def _open(self) -> None:
        module = self._import_websockets()
        self._closed_errors = (self._connection_closed, OSError)
        if self._encoding == "msgpack":
            self._packer = self._import_msgpack()

        ws = await self._new_connection(module)
        try:
            await self._handshake(ws)
        except BaseException:
            await ws.close()
            raise

        self._ws = ws
        if self._heartbeat_interval:
            self._heartbeat_task = asyncio.create_task(self._heartbeat())
        try:
            for channel, symbols in list(self._subscriptions.items()):
                await self._send_subscribe(channel, symbols)
        except BaseException:
            await self._teardown()
            raise

    def _import_websockets(self) -> Any:
        try:
            import websockets
            from websockets.exceptions import ConnectionClosed
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise DNSEValidationError(
                "websockets is not installed. Install the stream extra:\n"
                "  pip install -e '.[stream]'"
            ) from exc
        self._connection_closed = ConnectionClosed
        return websockets

    @staticmethod
    def _import_msgpack() -> Any:
        try:
            import msgpack
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise DNSEValidationError(
                "msgpack encoding requires msgpack; install the stream extra:\n"
                "  pip install -e '.[stream]'"
            ) from exc
        return msgpack

    async def _new_connection(self, module: Any) -> Any:
        factory = self._connect_factory or module.connect
        kwargs: dict[str, Any] = {
            "open_timeout": self._open_timeout,
            "ping_interval": None,
            "max_queue": 512,
        }
        return await factory(f"{self._url}?encoding={self._encoding}", **kwargs)

    async def _teardown(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        ws = self._ws
        self._ws = None
        if ws is not None:
            await ws.close()

    # -- protocol ----------------------------------------------------------

    async def _handshake(self, ws: Any) -> None:
        welcome = await self._receive(ws, timeout=self._open_timeout)
        if welcome.get("action") != "welcome":
            raise DNSEStreamError(
                "expected a welcome message, got: "
                f"{welcome.get('action') or welcome.get('T') or 'unknown'}"
            )
        if welcome.get("message"):
            _LOGGER.debug("stream session %s: %s", welcome.get("session_id"), welcome["message"])

        await self._send_to(ws, auth_payload(self._api_key, self._api_secret))
        while True:
            reply = await self._receive(ws, timeout=self._open_timeout)
            action = reply.get("action")
            if action == "auth_success":
                return
            if action == "error":
                raise DNSEStreamError(
                    str(reply.get("message") or "stream authentication failed"),
                    code=_opt_str(reply.get("code")),
                )

    async def subscribe(self, channel: str, symbols: Sequence[str] = ()) -> None:
        """Subscribe to a channel. Symbols are normalised to upper case."""
        if self._ws is None:
            raise DNSEStreamError("stream is not connected; call connect() first")
        normalised = [symbol.upper() for symbol in symbols]
        self._subscriptions[channel] = normalised
        await self._send_subscribe(channel, normalised)

    async def unsubscribe(self, channel: str, symbols: Sequence[str] = ()) -> None:
        """Unsubscribe from a channel, or from selected symbols of it."""
        if self._ws is None:
            raise DNSEStreamError("stream is not connected; call connect() first")
        normalised = [symbol.upper() for symbol in symbols]
        await self._send(
            {
                "action": "unsubscribe",
                "channels": [{"name": channel, "symbols": normalised}],
            }
        )
        if not normalised:
            self._subscriptions.pop(channel, None)
        elif channel in self._subscriptions:
            remaining = [
                symbol for symbol in self._subscriptions[channel] if symbol not in normalised
            ]
            if remaining:
                self._subscriptions[channel] = remaining
            else:
                self._subscriptions.pop(channel, None)

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield market-data messages until the stream is closed.

        The async generator survives reconnects; control frames are consumed
        and, when ``auto_reconnect`` is false, a dropped connection raises
        :class:`DNSEStreamError`.
        """
        if self._ws is None:
            raise DNSEStreamError("stream is not connected; call connect() first")

        while True:
            try:
                data = await self._receive(self._ws)
            except asyncio.CancelledError:
                raise
            except self._closed_errors as exc:
                await self._recover(exc)
                continue

            action = data.get("action")
            if action == "ping":
                payload: dict[str, Any] = {"action": "pong"}
                if "timestamp" in data:
                    payload["timestamp"] = data["timestamp"]
                await self._send(payload)
                continue
            if action in CONTROL_ACTIONS and "T" not in data:
                if action == "error":
                    raise DNSEStreamError(
                        str(data.get("message") or "stream error"),
                        code=_opt_str(data.get("code")),
                    )
                if action == "connection_expired":
                    _LOGGER.info("stream session expired; reconnecting")
                    await self._recover(None)
                    continue
                self._emit_control(data)
                continue
            yield data

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self.messages()

    # -- plumbing ----------------------------------------------------------

    async def _recover(self, exc: BaseException | None) -> None:
        if not self._auto_reconnect:
            raise DNSEStreamError(f"stream disconnected: {exc}" if exc else "stream disconnected")
        reason = exc.__class__.__name__ if exc else "expired"
        _LOGGER.warning("stream disconnected (%s); reconnecting", reason)
        await self._teardown()

        delay = 1.0
        while True:
            await self._sleep(delay)
            try:
                await self._open()
            except DNSEValidationError:
                raise
            except Exception as error:  # network or auth failure
                _LOGGER.warning("stream reconnect failed: %s", error)
                await self._teardown()
                delay = min(self._max_backoff, delay * 2)
                continue
            return

    async def _send_subscribe(self, channel: str, symbols: Sequence[str]) -> None:
        await self._send(
            {
                "action": "subscribe",
                "channels": [{"name": channel, "symbols": list(symbols)}],
            }
        )

    async def _send(self, payload: Mapping[str, Any]) -> None:
        if self._ws is None:
            raise DNSEStreamError("stream is not connected; call connect() first")
        await self._send_to(self._ws, payload)

    async def _send_to(self, ws: Any, payload: Mapping[str, Any]) -> None:
        await ws.send(self._encode(payload))

    async def _receive(self, ws: Any, *, timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            raw = await ws.recv()
        else:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return self._decode(raw)

    def _encode(self, payload: Mapping[str, Any]) -> Any:
        if self._packer is not None:
            return self._packer.packb(dict(payload))
        return json.dumps(dict(payload))

    def _decode(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, (bytes, bytearray)):
            if self._packer is None:
                raise DNSEStreamError("received a binary frame but encoding is json")
            data = self._packer.unpackb(bytes(raw), raw=False)
        else:
            data = json.loads(raw)
        if not isinstance(data, dict):
            raise DNSEStreamError(f"unexpected stream payload: {type(data).__name__}")
        return data

    def _emit_control(self, data: Mapping[str, Any]) -> None:
        if self._on_control is not None:
            self._on_control(data)

    async def _heartbeat(self) -> None:
        assert self._heartbeat_interval is not None
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await self._send({"action": "ping"})
            except Exception:  # connection is gone; the reader will reconnect
                return


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
