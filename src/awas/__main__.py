from __future__ import annotations

import uvicorn

from awas.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "awas.main:app",
        host=settings.server.host,
        port=settings.server.port,
        proxy_headers=settings.server.proxy_headers,
        forwarded_allow_ips=settings.server.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()

