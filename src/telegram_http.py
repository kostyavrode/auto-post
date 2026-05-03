"""
Shared HTTP client for all Telegram Bot API usage (polling + channel publish).

python-telegram-bot defaults to direct HTTPS; when api.telegram.org is blocked,
set TELEGRAM_PROXY_URL (or HTTPS_PROXY / HTTP_PROXY).
"""

import logging
import os
from urllib.parse import urlparse

from telegram.request import HTTPXRequest

logger = logging.getLogger(__name__)
_logged_proxy: bool = False


def build_telegram_http_request() -> HTTPXRequest:
    global _logged_proxy
    connect = float(os.environ.get("TELEGRAM_HTTP_CONNECT_TIMEOUT", "30"))
    read = float(os.environ.get("TELEGRAM_HTTP_READ_TIMEOUT", "60"))
    write = float(os.environ.get("TELEGRAM_HTTP_WRITE_TIMEOUT", "60"))
    pool = float(os.environ.get("TELEGRAM_HTTP_POOL_TIMEOUT", "10"))
    proxy_url = (
        os.environ.get("TELEGRAM_PROXY_URL", "").strip()
        or os.environ.get("HTTPS_PROXY", "").strip()
        or os.environ.get("HTTP_PROXY", "").strip()
        or None
    )
    if not _logged_proxy:
        _logged_proxy = True
        if proxy_url:
            u = urlparse(proxy_url)
            host = u.hostname or "?"
            port = f":{u.port}" if u.port else ""
            logger.info(
                "Telegram Bot API: using HTTP proxy %s://%s%s (credentials hidden)",
                u.scheme or "http",
                host,
                port,
            )
        else:
            logger.info(
                "Telegram Bot API: no HTTP proxy — direct connection to api.telegram.org "
                "(set TELEGRAM_PROXY_URL if Bot API is blocked)"
            )
    return HTTPXRequest(
        connect_timeout=connect,
        read_timeout=read,
        write_timeout=write,
        pool_timeout=pool,
        proxy_url=proxy_url,
    )
