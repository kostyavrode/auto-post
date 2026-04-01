"""
Import sources from config/sources.yml into the database on first run.
Sources already present (by url or channel) are skipped.
"""
import logging
import os
from pathlib import Path

import yaml

from src.db.models import get_db

logger = logging.getLogger(__name__)


async def import_sources_from_config() -> None:
    config_path = Path(os.getenv("CONFIG_DIR", "config")) / "sources.yml"
    if not config_path.exists():
        return

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    sources = data.get("sources", [])
    if not sources:
        return

    async with get_db() as db:
        for src in sources:
            src_type = src.get("type", "rss")
            name = src.get("name", "")
            url = src.get("url")
            channel = src.get("channel")
            enabled = 1 if src.get("enabled", True) else 0

            # Check if already exists
            if url:
                async with db.execute("SELECT id FROM sources WHERE url=?", (url,)) as cur:
                    if await cur.fetchone():
                        continue
            elif channel:
                async with db.execute(
                    "SELECT id FROM sources WHERE channel=?", (channel,)
                ) as cur:
                    if await cur.fetchone():
                        continue
            else:
                continue

            import json
            config_keys = ("article_selector", "title_selector", "body_selector",
                           "link_selector", "image_selector", "limit")
            extra = {k: src[k] for k in config_keys if k in src}

            await db.execute(
                """
                INSERT INTO sources (name, type, url, channel, config_json, enabled)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, src_type, url, channel, json.dumps(extra), enabled),
            )
            logger.info("Imported source from config: %s", name)

        await db.commit()
