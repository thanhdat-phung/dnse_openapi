from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from dnse_openapi.signing import (
    build_signature_header,
    build_signing_string,
    encode_signature,
    http_date,
    new_nonce,
    sign,
    signature_params,
)

DATE = "Fri, 15 May 2026 07:11:30 +0000"
NONCE = "c9a8f88b472c9721fde161e0d89df8cc"
EXPECTED_SIGNATURE = "ThcGFi8yakFJFqLGutstpVtDu1hD2do4qJO6sZuxnNA%3D"


def test_signing_string_is_exact() -> None:
    assert build_signing_string("GET", "/accounts", DATE, NONCE) == (
        "(request-target): get /accounts\n"
        "date: Fri, 15 May 2026 07:11:30 +0000\n"
        "nonce: c9a8f88b472c9721fde161e0d89df8cc"
    )


def test_signature_matches_reference_vector() -> None:
    signing_string = build_signing_string("GET", "/accounts", DATE, NONCE)
    assert sign("test-secret", signing_string) == EXPECTED_SIGNATURE


def test_encoded_signature_only_escapes_base64_specials() -> None:
    # Base64 of b"\xfb\xff" is "+/8=", and only + / = may be escaped.
    assert encode_signature(b"\xfb\xff") == "%2B%2F8%3D"


def test_signature_header_format() -> None:
    header = build_signature_header("my-key", EXPECTED_SIGNATURE, nonce=NONCE)
    assert header == (
        'Signature keyId="my-key",algorithm="hmac-sha256",'
        'headers="(request-target) date",'
        f'signature="{EXPECTED_SIGNATURE}",nonce="{NONCE}"'
    )


def test_method_and_custom_date_header_are_lowercased() -> None:
    value = build_signing_string(
        "POST", "/accounts/0001/orders", DATE, NONCE, date_header_name="X-Aux-Date"
    )
    assert value.startswith("(request-target): post /accounts/0001/orders\n")
    assert "x-aux-date: " in value

    header = build_signature_header(
        "k", "sig", nonce=NONCE, date_header_name="X-Aux-Date"
    )
    assert 'headers="(request-target) x-aux-date"' in header


def test_path_must_not_include_query() -> None:
    with pytest.raises(ValueError, match="query"):
        build_signing_string("GET", "/accounts?pageIndex=0", DATE, NONCE)


def test_nonce_is_32_hex_characters() -> None:
    nonce = new_nonce()
    assert len(nonce) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", nonce)


def test_http_date_uses_rfc1123_with_numeric_utc_offset() -> None:
    value = http_date(datetime(2026, 5, 15, 7, 11, 30, tzinfo=timezone.utc))
    assert value == DATE
    assert re.fullmatch(
        r"[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} \+0000", value
    )


def test_signature_params_regenerates_nonce_when_not_supplied() -> None:
    _, header1 = signature_params("k", "s", "GET", "/accounts")
    _, header2 = signature_params("k", "s", "GET", "/accounts")
    nonce1 = re.search(r'nonce="([0-9a-f]{32})"', header1)
    nonce2 = re.search(r'nonce="([0-9a-f]{32})"', header2)
    assert nonce1 and nonce2 and nonce1.group(1) != nonce2.group(1)
    assert header1 != header2
