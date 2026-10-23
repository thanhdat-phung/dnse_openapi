"""Stream live market data from the DNSE WebSocket.

Market data is only available over WebSocket; the REST ``/price/*`` routes are
not served by the sandbox host. This example works with sandbox keys because
the stream URL is picked from ``DNSE_BASE_URL`` (override with ``DNSE_WS_URL``).

Usage:
    .\.venv\Scripts\python.exe examples\market_stream.py
    .\.venv\Scripts\python.exe examples\market_stream.py HPG G1
    .\.venv\Scripts\python.exe examples\market_stream.py HPG G1 10

Press Ctrl+C to stop early. Sandbox feeds can be quiet outside trading hours.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from typing import Any

from dnse_openapi import DNSEClient, ohlc_channel, tick_channel, top_price_channel

DEFAULT_SYMBOL = "HPG"
DEFAULT_BOARD = "G1"
DEFAULT_COUNT = 5


def _price(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 1000:,.0f} VND"
    return "n/a"


def _show(message: Mapping[str, Any]) -> None:
    kind = message.get("T", "?")
    symbol = message.get("symbol", "?")
    if kind.startswith("ohlc"):
        print(
            f"[{kind}] {symbol} "
            f"O {_price(message.get('open'))} H {_price(message.get('high'))} "
            f"L {_price(message.get('low'))} C {_price(message.get('close'))} "
            f"V {message.get('volume')}"
        )
        return
    if "bid" in message:
        bid = (message.get("bid") or [{}])[0]
        offer = (message.get("offer") or [{}])[0]
        print(
            f"[{kind}] {symbol} best bid {_price(bid.get('price'))} x {bid.get('quantity')}, "
            f"best offer {_price(offer.get('price'))} x {offer.get('quantity')}"
        )
        return
    if "matchPrice" in message:
        print(
            f"[{kind}] {symbol} {_price(message.get('matchPrice'))} "
            f"x {message.get('matchQtty')}"
        )
        return
    print(f"[{kind}] {dict(message)}")


def main() -> None:
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else DEFAULT_SYMBOL
    board = sys.argv[2].upper() if len(sys.argv) > 2 else DEFAULT_BOARD
    count = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_COUNT

    async def run() -> None:
        client = DNSEClient.from_env()

        def on_control(message: Mapping[str, Any]) -> None:
            if message.get("action") == "subscribed":
                print(f"subscribed: {message.get('channel')}")

        stream = client.market_stream(heartbeat_interval=25.0, on_control=on_control)
        try:
            async with stream:
                await stream.subscribe(tick_channel(board), [symbol])
                await stream.subscribe(top_price_channel(board), [symbol])
                await stream.subscribe(ohlc_channel("1"), [symbol])
                print(f"streaming {symbol} / board {board} (Ctrl+C to stop)")
                seen = 0
                async for message in stream.messages():
                    _show(message)
                    seen += 1
                    if seen >= count:
                        break
        finally:
            client.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
