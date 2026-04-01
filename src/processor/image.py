import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

IMAGES_DIR = Path(os.getenv("DATA_DIR", "data")) / "images"
MAX_SIZE_BYTES = int(os.getenv("IMAGE_MAX_SIZE_MB", "10")) * 1024 * 1024
TIMEOUT = int(os.getenv("IMAGE_TIMEOUT", "30"))

VALID_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def download_image(url: str) -> Optional[str]:
    """
    Download an image from `url` and save it to IMAGES_DIR.
    Returns the local file path on success, or None on failure.
    """
    if not url:
        return None

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    url_hash = hashlib.md5(url.encode()).hexdigest()

    # Check if already downloaded
    for ext in EXT_MAP.values():
        existing = IMAGES_DIR / f"{url_hash}{ext}"
        if existing.exists():
            return str(existing)

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "NewsBot/1.0"},
        ) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "").split(";")[0].strip()
                if content_type not in VALID_CONTENT_TYPES:
                    logger.debug("Skipping non-image content-type: %s for %s", content_type, url)
                    return None

                ext = EXT_MAP.get(content_type, ".jpg")
                file_path = IMAGES_DIR / f"{url_hash}{ext}"

                total = 0
                chunks = []
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_SIZE_BYTES:
                        logger.debug("Image too large (>%dMB), skipping: %s", MAX_SIZE_BYTES // (1024*1024), url)
                        return None
                    chunks.append(chunk)

                file_path.write_bytes(b"".join(chunks))
                logger.debug("Downloaded image: %s -> %s", url, file_path)
                return str(file_path)

    except Exception as exc:
        logger.warning("Image download failed for %s: %s", url, exc)
        return None
