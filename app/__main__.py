"""Запуск: python -m app  (uvicorn на 127.0.0.1:8000)."""

from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.site_host,
        port=cfg.site_port,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_level=cfg.log_level.lower(),
    )


if __name__ == "__main__":
    main()
