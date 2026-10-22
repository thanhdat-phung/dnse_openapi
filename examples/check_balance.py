"""Print the cash and collateral balances for a DNSE sub-account.

Read-only: no trading token / OTP is required.

Run from the repository root:

    .\.venv\Scripts\python.exe examples\check_balance.py

Set DNSE_ACCOUNT_NO in .env, or let the script pick the first stock
(``dealAccount``) sub-account.
"""

from __future__ import annotations

from dnse_openapi import DNSEClient


def _money(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.0f} VND"
    return "n/a"


def main() -> None:
    with DNSEClient.from_env() as client:
        account_no = client.account_no
        if not account_no:
            accounts = client.accounts.get_accounts()
            stock_accounts = [a for a in accounts if a.get("dealAccount")]
            if not stock_accounts:
                raise SystemExit(
                    "No stock sub-account found; set DNSE_ACCOUNT_NO in .env"
                )
            account_no = str(stock_accounts[0]["id"])

        balance = client.accounts.get_balances(account_no)
        print(f"account: {account_no}")

        stock = balance.get("stock") or {}
        if stock:
            print("stock:")
            print(f"  total cash:        {_money(stock.get('totalCash'))}")
            print(f"  available cash:    {_money(stock.get('availableCash'))}")
            print(f"  withdrawable cash: {_money(stock.get('withdrawableCash'))}")
            print(f"  total debt:        {_money(stock.get('totalDebt'))}")
            print(f"  order secured:     {_money(stock.get('orderSecured'))}")

        derivative = balance.get("derivative") or {}
        if derivative:
            print("derivative:")
            print(f"  remaining collateral: {_money(derivative.get('remainSecure'))}")
            print(f"  used collateral:      {_money(derivative.get('usedSecure'))}")
            print(f"  loan debt:            {_money(derivative.get('totalLoanDebt'))}")

        bond = balance.get("bond") or {}
        if bond:
            print(f"bond value: {_money(bond.get('totalValue'))}")

        egg = balance.get("egg") or {}
        if egg:
            print(f"egg value: {_money(egg.get('totalValue'))}")


if __name__ == "__main__":
    main()
