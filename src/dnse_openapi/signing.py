"""HTTP Signature construction for DNSE OpenAPI.

DNSE uses HTTP Signatures with an HMAC digest. The signing string is::

    (request-target): get /accounts
    date: Fri, 15 May 2026 07:11:30 +0000
    nonce: c9a8f88b472c9721fde161e0d89df8cc

Lines are separated by ``\\n`` with no trailing newline. The method and header
names are lower-case. Only the URL path is signed - query parameters and the
JSON body are not part of the signature.

The digest is Base64 encoded and then percent-encoded for ``+``, ``/`` and
``=`` only, matching DNSE's documented ``ENCODED_SIGNATURE`` format.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

_ALGORITHMS: dict[str, Callable[..., Any]] = {
    "hmac-sha256": hashlib.sha256,
    "hmac-sha384": hashlib.sha384,
    "hmac-sha512": hashlib.sha512,
    "hmac-sha1": hashlib.sha1,
}

DEFAULT_ALGORITHM = "hmac-sha256"


def new_nonce() -> str:
    """Return a fresh 32-character hex nonce (UUID4 without dashes)."""
    return uuid4().hex


def http_date(now: datetime | None = None) -> str:
    """Format a timezone-aware datetime as an RFC 1123 date with ``+0000``.

    DNSE rejects requests whose ``Date`` header differs from its own clock by
    more than one minute, so callers should generate this immediately before
    sending.
    """
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def build_signing_string(
    method: str,
    path: str,
    date_value: str,
    nonce: str,
    *,
    date_header_name: str = "Date",
) -> str:
    """Build the exact string that is HMAC-signed.

    ``path`` must be the request path only (for example ``/accounts``), without
    a query string. This is enforced so a query can never silently corrupt the
    signature.
    """
    if "?" in path or "#" in path:
        raise ValueError("path must not contain a query string or fragment")
    if not path.startswith("/"):
        raise ValueError("path must start with '/'")
    if not date_header_name:
        raise ValueError("date_header_name must not be empty")

    header_key = date_header_name.lower()
    return (
        f"(request-target): {method.lower()} {path}\n"
        f"{header_key}: {date_value}\n"
        f"nonce: {nonce}"
    )


def headers_list(date_header_name: str = "Date") -> str:
    """Value for the ``headers=`` parameter of the X-Signature header."""
    return f"(request-target) {date_header_name.lower()}"


def encode_signature(digest: bytes) -> str:
    """Base64-encode a digest and percent-encode ``+``, ``/`` and ``=``."""
    encoded = base64.b64encode(digest).decode("ascii")
    return encoded.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")


def sign(
    api_secret: str,
    signing_string: str,
    *,
    algorithm: str = DEFAULT_ALGORITHM,
) -> str:
    """Return the URL-encoded HMAC signature for ``signing_string``."""
    try:
        digestmod = _ALGORITHMS[algorithm]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"unsupported signature algorithm: {algorithm}") from exc

    digest = hmac.new(
        api_secret.encode("utf-8"),
        signing_string.encode("utf-8"),
        digestmod,
    ).digest()
    return encode_signature(digest)


def build_signature_header(
    api_key: str,
    signature: str,
    *,
    nonce: str,
    algorithm: str = DEFAULT_ALGORITHM,
    date_header_name: str = "Date",
) -> str:
    """Build the full value of the ``X-Signature`` header."""
    return (
        f'Signature keyId="{api_key}",'
        f'algorithm="{algorithm}",'
        f'headers="{headers_list(date_header_name)}",'
        f'signature="{signature}",'
        f'nonce="{nonce}"'
    )


def signature_params(
    api_key: str,
    api_secret: str,
    method: str,
    path: str,
    *,
    date_value: str | None = None,
    nonce: str | None = None,
    algorithm: str = DEFAULT_ALGORITHM,
    date_header_name: str = "Date",
) -> tuple[str, str]:
    """Return ``(date_value, x_signature_header)`` for one request.

    A new nonce (and therefore a new signature) is produced on every call, so
    retries must call this function again instead of reusing headers.
    """
    date_value = date_value or http_date()
    nonce = nonce or new_nonce()
    signing_string = build_signing_string(
        method, path, date_value, nonce, date_header_name=date_header_name
    )
    signature = sign(api_secret, signing_string, algorithm=algorithm)
    header = build_signature_header(
        api_key,
        signature,
        nonce=nonce,
        algorithm=algorithm,
        date_header_name=date_header_name,
    )
    return date_value, header


def url_encode_base64(value: str) -> str:
    """Percent-encode the three Base64 characters DNSE requires."""
    return value.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")
