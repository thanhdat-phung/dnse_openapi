# dnse-openapi

Clean-room Python client and local server for the **DNSE OpenAPI (LightSpeed)** platform.

This repository targets the current API documented at
<https://developers.dnse.com.vn/docs/guide/intro/api_platform>. It deliberately does **not**
reuse the legacy `api.dnse.com.vn` / `order-service` endpoints: the base URL, authentication
model, paths and payloads are all different.

- Signed requests (`X-Api-Key`, `X-Signature`, `Date`, `version`) with a fresh nonce per attempt
- Email OTP, Smart OTP and Smart OTP Handoff flows, plus an 8-hour trading-token cache
- Validated NORMAL, STOP and OCO order models
- Replace / cancel / close / reverse endpoints
- Accounts, balances, loan packages, PPSE, positions, order history and market data
- Optional local FastAPI server that mirrors DNSE paths, so official examples work unchanged
- Sandbox-first workflow; no production call is made by the test suite

## Requirements

- Python 3.10+
- DNSE LightSpeed API credentials (production or sandbox)

## Install

```bash
git clone <this-repo> dnse_openapi
cd dnse_openapi
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -e ".[server,dev]"
```

The core client only needs `httpx` and `pydantic`. The `server` extra adds FastAPI, Uvicorn and
dotenv; `dev` adds pytest, ruff and mypy.

## Configure

Copy `.env.example` to `.env` and fill in the values:

```dotenv
DNSE_API_KEY=...
DNSE_API_SECRET=...

# Start against sandbox, not production:
DNSE_BASE_URL=https://sb-openapi.dnse.com.vn

DNSE_API_VERSION=2026-07-23
DNSE_ACCOUNT_NO=0001179019
```

`DNSE_API_KEY` and `DNSE_API_SECRET` are the credentials issued when you register LightSpeed
API (or the separate Sandbox keys). They are **not** your login username/password. Importing the
package has no side effects. `DNSEClient.from_env()` loads `.env` from the current directory or
a parent when `python-dotenv` is installed (the `server` and `dev` extras include it). Pass
`load_env_file=False` to skip that lookup, or set the variables in your shell.

## Sandbox first

Sandbox uses the same paths and signing rules as production, with a different host and a
separate key pair:

```dotenv
DNSE_BASE_URL=https://sb-openapi.dnse.com.vn
DNSE_API_KEY=<sandbox-key>
DNSE_API_SECRET=<sandbox-secret>
```

On Sandbox, no real email or app notification is sent. Call the trading-token endpoint with
your chosen `otpType` and the fixed passcode `666666`:

```python
from dnse_openapi import DNSEClient

with DNSEClient.from_env() as client:
    client.auth.create_trading_token("email_otp", "666666")
    print(client.accounts.get_accounts())
```

The sandbox guide shows the token response as `trading-token`, while the OpenAPI spec and
production responses use `tradingToken`. The client accepts either key.

## Quick start

```python
from dnse_openapi import DNSEClient, MarketType, NormalOrder

with DNSEClient.from_env() as client:
    # 1. Get identifiers from DNSE instead of hard-coding them.
    profile = client.accounts.get_accounts()
    account_no = next(
        account["id"] for account in profile["accounts"] if account.get("dealAccount")
    )

    # 2. Authenticate the trading session (2FA).
    #    Requires DNSE_OTP_IMAP_USER / DNSE_OTP_IMAP_PASSWORD for Email OTP.
    client.login_with_email_otp()
    # or: client.login_with_smart_otp("123456")
    # or: client.login_with_handoff()

    # 3. Pick the loan package for the symbol.
    packages = client.accounts.get_loan_packages(account_no, MarketType.STOCK, "HPG")
    loan_package_id = packages["loanPackages"][0]["id"]

    # 4. Place a NORMAL limit order. Prices are VND (not thousands).
    order = NormalOrder(
        symbol="HPG",
        side="NB",          # NB = buy, NS = sell
        order_type="LO",
        quantity=100,
        price=27_500,
        loan_package_id=loan_package_id,
    )
    result = client.orders.place_order(account_no, MarketType.STOCK, order)
    print(result)
```

### Check balance

Balances are read-only, so no OTP or trading token is needed:

```python
from dnse_openapi import DNSEClient

with DNSEClient.from_env() as client:
    profile = client.accounts.get_accounts()

    # Pick the stock sub-account; use derivativeAccount for derivatives.
    account_no = next(
        account["id"] for account in profile["accounts"] if account.get("dealAccount")
    )

    balance = client.accounts.get_balances(account_no)
    print("available cash:", balance["stock"]["availableCash"])
    print("total cash:    ", balance["stock"]["totalCash"])
    print("withdrawable:  ", balance["stock"]["withdrawableCash"])
```

The response has separate sections: `stock`, `derivative`, `bond`, and `egg`.
Useful stock fields are `totalCash`, `availableCash`, `withdrawableCash`,
`totalDebt`, and `orderSecured`. The derivative section uses `remainSecure`,
`usedSecure`, and `totalLoanDebt`.

A complete script is in `examples/check_balance.py`:

```powershell
.\.venv\Scripts\python.exe examples\check_balance.py
```

### Market data

Market data is read-only and signed; no OTP or trading token is needed.

```python
import time

from dnse_openapi import DNSEClient

with DNSEClient.from_env() as client:
    symbol, board = "HPG", "G1"

    # Reference, ceiling and floor prices (in thousands of VND).
    secdef = client.accounts.get_security_definition(symbol, board)
    print(secdef[0]["basicPrice"], secdef[0]["ceilingPrice"], secdef[0]["floorPrice"])

    # Latest matched trade.
    trade = client.accounts.get_latest_trade(symbol, board)["trades"][0]
    print(trade["matchPrice"], trade["matchQtty"], trade["time"])

    # Latest bid/ask depth.
    quote = client.accounts.get_latest_quote(symbol, board)["quotes"][0]
    print("best bid:  ", quote["bid"][0])
    print("best offer:", quote["offer"][0])

    # Daily candles for the last 30 days.
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
    print("timestamps:", ohlc["t"])
    print("closes:    ", ohlc["c"])
```

For `get_ohlc`, the first argument is the **market type** (`STOCK`, `DERIVATIVE`, or `INDEX`),
not the candle size. Put the candle size in `query["resolution"]`: `1`, `3`, `5`, `15`, `30`,
`1h`, `1D`, or `1W`.

| Data | Method |
|---|---|
| Reference / ceiling / floor | `get_security_definition(symbol, board_id)` |
| Latest trade | `get_latest_trade(symbol, board_id)` |
| Historical trades | `get_trades(symbol, ...)` |
| Latest order book | `get_latest_quote(symbol, board_id)` |
| Historical quotes | `get_quotes(symbol, ...)` |
| OHLCV candles | `get_ohlc(market_type, query)` |
| Market index history | `get_market_index(index_name, ...)` |
| Expected / close price | `get_expected_price(...)`, `get_close_price(...)` |
| Foreign trading | `get_foreign_trading(symbol, ...)` |
| Instrument search | `get_instruments(symbol=..., market_id=...)` |
| Trading sessions / dates | `get_trading_session(...)`, `get_working_dates()` |

Stock prices from these endpoints are in **thousands of VND**, so `21.25` means
`21,250 VND`. Order prices must be sent in VND (`21_250`).

A complete runnable script is in `examples/market_data.py`:

```powershell
.\.venv\Scripts\python.exe examples\market_data.py HPG G1
```

### STOP order

STOP orders use `orderCategory=STOP` and carry both the trigger fields and the fields of the
regular order that will be sent to the exchange when triggered.

```python
from datetime import datetime, timedelta, timezone
from dnse_openapi import StopOrder

order = StopOrder(
    symbol="41I1G8000",
    side="NS",
    order_type="LO",
    quantity=3,
    price=1_900,
    loan_package_id=2_278,
    stop_price=1_700,
    condition_operator="<=",          # trigger when market price <= 1700
    duration_type="GTD",              # only GTD is accepted
    duration_date_time=datetime.now(timezone(timedelta(hours=7))) + timedelta(days=1),
)
client.orders.place_order(account_no, "DERIVATIVE", order)
```

### OCO order (derivatives only)

```python
from dnse_openapi import OCOOrder

order = OCOOrder(
    symbol="41I1G8000",
    side="NB",
    quantity=3,
    price=1_990,            # take-profit price
    stop_price=2_000,       # trigger price
    stop_order_price=2_005, # stop-loss order price
    loan_package_id=2_278,
)
client.orders.place_order(account_no, "DERIVATIVE", order)
```

### Replace and cancel

```python
client.orders.replace_order(account_no, "511", "STOCK", {"price": 27_600, "quantity": 100})
client.orders.cancel_order(account_no, "511", "STOCK")

# STOP / OCO orders must be cancelled while they are still in `New` state.
client.orders.cancel_order(account_no, "stop-id", "DERIVATIVE", order_category="STOP")
```

## Validation rules enforced locally

| Rule | Behaviour |
|---|---|
| `price > 0` for `LO` | rejected otherwise |
| `price == 0` for ATO/ATC/MTL/MOK/MAK/PLO | rejected otherwise |
| `quantity > 0` | rejected otherwise |
| `loanPackageId > 0` | rejected otherwise |
| STOP only for STOCK/DERIVATIVE | rejected for BOND |
| OCO only for DERIVATIVE | rejected otherwise |
| STOP `durationType` must be `GTD` | enforced by the model |
| OCO `durationType` must be `DAY` | enforced by the model |
| STOP expiry must be timezone-aware | rejected otherwise |
| Replace requires at least one field | rejected otherwise |
| Derivative replace accepts one of price/quantity | rejected if both are sent |

Stock prices returned by `/price/{symbol}/secdef` are in **thousands of VND**. Multiply them
(use `dnse_openapi.models.to_vnd`) before sending an order.

## Local server

The `dnse-openapi` command is installed into the project venv, not into the system
Python PATH. Run it from the repository root with the venv active:

```powershell
cd C:\Users\dat\Downloads\Documents\Books\Trading\dnse_openapi
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
notepad .env          # fill in your DNSE sandbox keys
dnse-openapi
```

If PowerShell blocks activation, call the venv executable directly:

```powershell
.\.venv\Scripts\dnse-openapi.exe
```

Do **not** run `python -m dnse_openapi.server` from `src\dnse_openapi` with the
system Python; that interpreter does not have the package or server extras. The
venv equivalent, run from the repository root, is:

```powershell
.\.venv\Scripts\python.exe -m dnse_openapi.server
```

On macOS/Linux, activate with `source .venv/bin/activate` and run the same
commands.

It listens on `127.0.0.1:8000` by default and mirrors DNSE paths:

```bash
# Send an Email OTP (upstream call)
curl -X POST http://127.0.0.1:8000/registration/send-email-otp

# Exchange the OTP for a trading token; it is cached in this process
curl -X POST http://127.0.0.1:8000/registration/trading-token \
  -H "Content-Type: application/json" \
  -d '{"otpType":"email_otp","passcode":"123456"}'

# Place a NORMAL order (uses the cached trading token)
curl -X POST "http://127.0.0.1:8000/accounts/0001179019/orders?marketType=STOCK&orderCategory=NORMAL" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"HPG","side":"NB","orderType":"LO","quantity":100,"price":27500,"loanPackageId":5757}'

# Read endpoints
curl "http://127.0.0.1:8000/accounts"
curl "http://127.0.0.1:8000/accounts/0001179019/balances"
curl "http://127.0.0.1:8000/accounts/0001179019/orders?marketType=STOCK&orderCategory=NORMAL&pageIndex=0&pageSize=10"
```

If `DNSE_SERVER_TOKEN` is set, every request must include either
`X-Local-Token: <token>` or `Authorization: Bearer <token>`. Keep this set if the port is
reachable from anything other than your own user account. OpenAPI docs are at `/docs`.

## Spec compliance

| Spec item | Implementation |
|---|---|
| Base URL `https://openapi.dnse.com.vn` | `config.DEFAULT_BASE_URL`; sandbox constant `SANDBOX_BASE_URL` |
| `X-Api-Key`, `X-Signature`, `Date`, `version` | `signing.py` / `transport.py` |
| Signing string: `(request-target)` + `date` + `nonce` | `build_signing_string` (path only, no body/query) |
| HMAC-SHA256, Base64, escape `+ / =` | `sign` / `encode_signature` |
| Fresh `Date` + nonce per request | regenerated on every retry attempt |
| Email OTP | `POST /registration/send-email-otp` |
| Smart OTP handoff | `POST /registration/smart-otp/handoff` |
| Trading token (`otpType`, `passcode`) | `POST /registration/trading-token`, cached 8 h |
| NORMAL / STOP / OCO | `POST /accounts/{accountNo}/orders?marketType=&orderCategory=` |
| Replace / cancel | `PUT` / `DELETE /accounts/{accountNo}/orders/{orderId}` |
| Close / reverse position | `POST /positions/{positionId}/close|reverse` |
| Accounts, balances, loans, PPSE, positions, orders, history | `accounts.py` |
| Market data (`secdef`, OHLC, trades, quotes, index, sessions…) | `AccountClient` methods |
| Rate limits (429 with `Retry-After`, daily 403 `OA-401`) | typed errors + bounded retry/backoff |
| Error body `{status, code, message}` | mapped to `DNSEAPIError` subclasses |

Defaults follow DNSE's official sample SDK: `version: 2026-07-23`, `Date` header name. The
Smart OTP handoff and reverse-position calls use `2026-01-01`, matching the SDK's per-endpoint
overrides. The default is configurable with `DNSE_API_VERSION`, and the date header name with
`DNSE_DATE_HEADER` (some spec snapshots use `X-Aux-Date`).

## Not implemented (yet)

- WebSocket streaming (`wss://ws-openapi.dnse.com.vn`) for order/position/market-data events
- Broker/SACO endpoints
- Typed models for PnL configuration payloads (accepted as raw dictionaries)
- Automatic sandbox/production switching beyond changing `DNSE_BASE_URL`

These are intentionally out of scope for the first cut; the `raw()` escape hatch on
`client.accounts` lets you call any signed endpoint in the meantime.

## Security notes

- Never commit `.env`, API secrets, or trading tokens. `.gitignore` covers them.
- Keep the machine clock synchronized (NTP). DNSE rejects a `Date` header that differs from
  its clock by more than ±1 minute, and every request is signed with the current UTC time.
- Prefer Email OTP with an app password stored in the OS keychain or environment.
- `FileTokenStore` is opt-in; a trading token is a bearer credential. The default is an
  in-memory store.
- The transport never logs headers or bodies. Only method/path/status appear at DEBUG level.
- Start with sandbox keys (`https://sb-openapi.dnse.com.vn`) and verify the full order lifecycle
  there before pointing at production.

## Develop

```bash
pytest                 # signing vectors, transport, models, auth, server
ruff check .
mypy
```

The test suite uses `httpx.MockTransport`; no DNSE account or network access is required.

## Layout

```
src/dnse_openapi/
  signing.py      # HTTP Signature construction
  transport.py    # signed requests, retries, error mapping
  models.py       # enums + validated order payloads
  auth.py         # OTP flows, trading-token cache
  accounts.py     # read endpoints
  orders.py       # place / replace / cancel / close / reverse
  client.py       # facade and env construction
  otp/email.py    # optional IMAP OTP reader
  server/         # local FastAPI facade
tests/            # offline test suite
examples/         # runnable snippets
```

## License

MIT. See [LICENSE](LICENSE).
