"""Place a STOP order on a derivative contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dnse_openapi import DNSEClient, MarketType, StopOrder

VIETNAM = timezone(timedelta(hours=7))


def main() -> None:
    with DNSEClient.from_env() as client:
        # Acquire a trading token first (see login_email_otp.py). On sandbox:
        # client.auth.create_trading_token("email_otp", "666666")
        account_no = client.require_account_no()
        expiry = (datetime.now(VIETNAM) + timedelta(days=1)).replace(
            hour=14, minute=30, second=0, microsecond=0
        )
        order = StopOrder(
            symbol="41I1G8000",
            side="NS",
            order_type="LO",
            quantity=3,
            price=1_900,
            loan_package_id=2_278,
            stop_price=1_700,
            condition_operator="<=",
            duration_type="GTD",
            duration_date_time=expiry,
        )
        print(client.orders.place_order(account_no, MarketType.DERIVATIVE, order))


if __name__ == "__main__":
    main()
