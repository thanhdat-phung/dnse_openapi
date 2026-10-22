"""Authenticate with Email OTP and cache the trading token.

Requires DNSE_OTP_IMAP_USER and DNSE_OTP_IMAP_PASSWORD (Gmail app password).
"""

from __future__ import annotations

from dnse_openapi import DNSEClient


def main() -> None:
    with DNSEClient.from_env() as client:
        token = client.login_with_email_otp()
        print(f"trading token acquired (expires at {client.auth.expires_at}): {token[:8]}...")
        print("accounts:", client.accounts.get_accounts())


if __name__ == "__main__":
    main()
