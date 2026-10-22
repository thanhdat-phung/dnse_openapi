from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from dnse_openapi import DNSEClient


@pytest.fixture
def make_client() -> Callable[..., DNSEClient]:
    """Build a client whose HTTP layer is a MockTransport handler."""

    def _make(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> DNSEClient:
        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        return DNSEClient("test-key", "test-secret", http_client=http_client, **kwargs)

    return _make
