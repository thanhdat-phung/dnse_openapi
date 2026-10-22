"""Signed HTTP transport with retries and error mapping."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import httpx

from ._version import __version__
from .config import DEFAULT_API_VERSION, DEFAULT_BASE_URL
from .errors import DNSETransportError, error_from_response
from .signing import DEFAULT_ALGORITHM, http_date, signature_params

logger = logging.getLogger("dnse_openapi")

_RETRY_STATUSES = frozenset({500, 502, 503, 504})
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
_RESERVED_HEADERS = frozenset({"x-api-key", "x-signature", "version"})


@dataclass(frozen=True, slots=True)
class APIResponse:
    status_code: int
    data: Any
    headers: Mapping[str, str] = field(default_factory=dict)
    request_id: str | None = None


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        cleaned[key] = value.value if isinstance(value, Enum) else value
    return cleaned or None


def _parse_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response.text


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        seconds = when.timestamp() - time.time()
    return max(0.0, seconds)


class Transport:
    """Sends signed requests to DNSE and maps failures to typed exceptions.

    Every attempt is signed with a fresh ``Date`` and nonce. Only the URL path is
    signed, matching DNSE's HTTP Signature contract.

    ``http_client`` and ``sleep`` are injectable for tests. An injected client
    does not need a ``base_url`` because absolute URLs are always used.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
        date_header_name: str = "Date",
        algorithm: str = DEFAULT_ALGORITHM,
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        max_backoff: float = 30.0,
        http_client: httpx.Client | None = None,
        clock: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret are required")

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute http(s) URL")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a path, query or fragment")

        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._date_header_name = date_header_name
        self._algorithm = algorithm
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._clock = clock or (lambda: http_date())
        self._sleep = sleep or time.sleep
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": f"dnse-openapi-python/{__version__}",
            },
        )

    # -- properties ---------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_version(self) -> str:
        return self._api_version

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- request building ---------------------------------------------------

    def _headers(
        self,
        method: str,
        path: str,
        *,
        version: str | None,
        json_body: Any,
        extra: Mapping[str, str] | None,
    ) -> dict[str, str]:
        date_value = self._clock()
        if not isinstance(date_value, str):
            date_value = http_date(date_value)
        date_value, signature_header = signature_params(
            self._api_key,
            self._api_secret,
            method,
            path,
            date_value=date_value,
            algorithm=self._algorithm,
            date_header_name=self._date_header_name,
        )

        headers: dict[str, str] = {
            self._date_header_name: date_value,
            "X-Signature": signature_header,
            "x-api-key": self._api_key,
            "version": version or self._api_version,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        for key, value in (extra or {}).items():
            lowered = key.lower()
            if lowered in _RESERVED_HEADERS or lowered == self._date_header_name.lower():
                raise ValueError(f"header {key!r} is managed by the transport")
            headers[key] = value
        return headers

    # -- public API ---------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        version: str | None = None,
    ) -> APIResponse:
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        if "?" in path or "#" in path:
            raise ValueError("pass query parameters via params=, not in the path")

        method = method.upper()
        idempotent = method in _IDEMPOTENT_METHODS
        attempts = self._max_retries if retries is None else max(0, retries)
        url = f"{self._base_url}{path}"
        clean_params = _clean_params(params)
        content = (
            json.dumps(json_body, separators=(",", ":"), ensure_ascii=False)
            if json_body is not None
            else None
        )

        for attempt in range(attempts + 1):
            request_headers = self._headers(
                method, path, version=version, json_body=json_body, extra=headers
            )
            kwargs: dict[str, Any] = {
                "params": clean_params,
                "content": content,
                "headers": request_headers,
            }
            if timeout is not None:
                kwargs["timeout"] = timeout

            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                if idempotent and attempt < attempts:
                    self._sleep(self._delay(attempt, None))
                    continue
                raise DNSETransportError(f"request failed: {exc}") from exc

            retryable = response.status_code == 429 or (
                idempotent and response.status_code in _RETRY_STATUSES
            )
            if retryable and attempt < attempts:
                delay = self._delay(attempt, response.headers.get("Retry-After"))
                logger.warning(
                    "retrying %s %s after HTTP %s in %.2fs",
                    method,
                    path,
                    response.status_code,
                    delay,
                )
                self._sleep(delay)
                continue

            request_id = response.headers.get("X-Request-Id")
            if response.is_success:
                logger.debug("%s %s -> %s", method, path, response.status_code)
                return APIResponse(
                    status_code=response.status_code,
                    data=_parse_body(response),
                    headers=dict(response.headers),
                    request_id=request_id,
                )

            payload = _parse_body(response)
            logger.debug("%s %s -> %s", method, path, response.status_code)
            raise error_from_response(
                response.status_code, payload, headers=response.headers
            )

        # The loop always returns or raises; this keeps type checkers happy.
        raise AssertionError("unreachable")  # pragma: no cover

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        hinted = _retry_after(retry_after)
        if hinted is not None:
            return min(hinted, self._max_backoff)
        base = self._backoff * (2**attempt)
        jitter: float = random.uniform(0.5, 1.0)
        return float(min(self._max_backoff, base * jitter))

    def get(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request("DELETE", path, **kwargs)
