"""Place a NORMAL limit order using sandbox or production credentials."""

from __future__ import annotations

from dnse_openapi import DNSEClient, MarketType, NormalOrder


def main() -> None:
    with DNSEClient.from_env() as client:
        # Acquire a trading token first (see login_email_otp.py). On sandbox:
        # client.auth.create_trading_token("email_otp", "666666")
        account_no = client.require_account_no()
        packages = client.accounts.get_loan_packages(account_no, MarketType.STOCK, "HPG")
        loan_package_id = packages["loanPackages"][0]["id"]

        order = NormalOrder(
            symbol="HPG",
            side="NB",
            order_type="LO",
            quantity=100,
            price=27_500,
            loan_package_id=loan_package_id,
        )
        print(client.orders.place_order(account_no, MarketType.STOCK, order))


if __name__ == "__main__":
    main()
