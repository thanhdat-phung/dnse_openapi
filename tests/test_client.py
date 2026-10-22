from __future__ import annotations

import os
from pathlib import Path

import pytest

from dnse_openapi import DNSEClient

_ENV_KEYS = (
    "DNSE_API_KEY",
    "DNSE_API_SECRET",
    "DNSE_ACCOUNT_NO",
    "DNSE_BASE_URL",
)


def test_from_env_loads_dotenv_from_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DNSE_API_KEY=dotenv-key",
                "DNSE_API_SECRET=dotenv-secret",
                "DNSE_ACCOUNT_NO=0001179019",
                "DNSE_BASE_URL=https://sb-openapi.dnse.com.vn",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    try:
        for key in _ENV_KEYS:
            os.environ.pop(key, None)

        with DNSEClient.from_env() as client:
            assert client.account_no == "0001179019"
            assert client.transport.base_url == "https://sb-openapi.dnse.com.vn"
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
