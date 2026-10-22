"""Print a market-data snapshot for a DNSE symbol.

Read-only: no OTP or trading token is needed.

Usage:
    .\.venv\Scripts\python.exe examples\market_data.py HPG
    .\.venv\Scripts\python.exe examples\market_data.py HPG G1

Price fields returned by these endpoints are in thousands of VND.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone

from dnse_openapi import DNSEClient

DEFAULT_SYMBOL = "HPG"
DEFAULT_BOARD = "G1"


def _price(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 1000:,.0f} VND"
    return "n/a"


def _first(payload: object, key: str) -> Mapping[str, object] | None:
    if not isinstance(payload, Mapping):
        return None
    items = payload.get(key)
    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    return None


def _list(payload: object, key: str) -> list[object]:
    if isinstance(payload, Mapping):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _best(quote: Mapping[str, object], side: str) -> Mapping[str, object]:
    levels = quote.get(side)
    if isinstance(levels, list) and levels and isinstance(levels[0], Mapping):
        return levels[0]
    return {}


def main() -> None:
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else DEFAULT_SYMBOL
    board = sys.argv[2].upper() if len(sys.argv) > 2 else DEFAULT_BOARD

    with DNSEClient.from_env() as client:
        secdef = client.accounts.get_security_definition(symbol, board)
        if isinstance(secdef, list) and secdef and isinstance(secdef[0], Mapping):
            info = secdef[0]
            print(f"{symbol} / board {board}")
            print(f"  reference: {_price(info.get('basicPrice'))}")
            print(f"  ceiling:   {_price(info.get('ceilingPrice'))}")
            print(f"  floor:     {_price(info.get('floorPrice'))}")

        trade = _first(client.accounts.get_latest_trade(symbol, board), "trades")
        if trade:
            print(
                f"  last trade: {_price(trade.get('matchPrice'))} "
                f"x {trade.get('matchQtty')} at {trade.get('time')}"
            )

        quote = _first(client.accounts.get_latest_quote(symbol, board), "quotes")
        if quote:
            bid = _best(quote, "bid")
            offer = _best(quote, "offer")
            print(f"  best bid:   {_price(bid.get('price'))} x {bid.get('quantity')}")
            print(f"  best offer: {_price(offer.get('price'))} x {offer.get('quantity')}")

        now = int(time.time())
        ohlc = client.accounts.get_ohlc(
            "STOCK",
            {
                "symbol": symbol,
                "resolution": "1D",
                "from": now - 30 * 24 * 3600,
                "to": now,
            },
        )
        times = [value for value in _list(ohlc, "t") if isinstance(value, int)]
        closes = _list(ohlc, "c")
        bars = list(zip(times, closes, strict=False))[-5:]
        if bars:
            print("  last daily closes:")
            for timestamp, close in bars:
                day = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")
                print(f"    {day}: {_price(close)}")


if __name__ == "__main__":
    main()
