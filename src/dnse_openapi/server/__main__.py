"""``dnse-openapi`` console entry point."""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - depends on optional extra
        pass
    else:
        load_dotenv()

    try:
        import uvicorn
    except ImportError:  # pragma: no cover
        sys.stderr.write(
            "uvicorn is not installed. Install the server extra:\n"
            "  pip install -e '.[server]'\n"
        )
        raise SystemExit(1) from None

    from .._version import __version__
    from ..config import Settings
    from .app import create_app

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        sys.stderr.write(
            "Copy .env.example to .env, fill in your DNSE sandbox keys, then retry.\n"
        )
        raise SystemExit(2) from None

    app = create_app(settings=settings)
    print(f"DNSE OpenAPI local server v{__version__}")
    print(f"  upstream: {settings.base_url} (version {settings.api_version})")
    print(f"  listening: http://{settings.server_host}:{settings.server_port}")
    if not settings.server_token:
        print("  warning: DNSE_SERVER_TOKEN is unset; any local process can trade")
    uvicorn.run(
        app,
        host=settings.server_host,
        port=settings.server_port,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
