from __future__ import annotations

from email.message import EmailMessage

from dnse_openapi.otp import extract_otp
from dnse_openapi.otp.email import _message_text, _message_time


def test_extract_vietnamese_labelled_otp() -> None:
    assert extract_otp("Mã OTP của bạn là: 123456") == "123456"
    assert extract_otp("Mã xác thực: 654321. Không chia sẻ.") == "654321"


def test_extract_english_labelled_otp() -> None:
    assert extract_otp("Your OTP code is 987654. It expires in 2 minutes.") == "987654"
    assert extract_otp("passcode: 112233") == "112233"


def test_extract_generic_six_digit_fallback() -> None:
    assert extract_otp("Use 445566 to sign in.") == "445566"


def test_extract_returns_none_without_code() -> None:
    assert extract_otp("No code here") is None
    assert extract_otp("") is None


def test_extract_ignores_six_digits_inside_an_account_id() -> None:
    assert extract_otp("Account 064C950519 has no code") is None
    assert extract_otp("Order 41I1G8000 was filled") is None


def test_message_time_reads_the_date_header() -> None:
    message = EmailMessage()
    message["Date"] = "Fri, 15 May 2026 07:11:30 +0000"
    assert _message_time(message) == 1778829090.0


def test_message_text_prefers_plain_part() -> None:
    message = EmailMessage()
    message["Subject"] = "Email OTP"
    message.set_content("Plain OTP: 123456")
    message.add_alternative("<p>HTML OTP: 999999</p>", subtype="html")
    assert "123456" in _message_text(message)


def test_message_text_strips_html_when_only_html() -> None:
    message = EmailMessage()
    message.set_content("<p>Your <b>OTP</b> is 778899</p>", subtype="html")
    text = _message_text(message)
    assert extract_otp(text) == "778899"
