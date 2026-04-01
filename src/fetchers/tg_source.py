import logging
import os
from typing import List, Optional

from .rss import RawArticle

logger = logging.getLogger(__name__)


async def fetch_telegram(source: dict, client) -> List[RawArticle]:
    """
    Fetch recent messages from a Telegram channel using a Telethon client.
    `client` is an already-connected telethon.TelegramClient instance.
    """
    channel = source.get("channel", "")
    source_name = source.get("name", channel)
    source_id = source.get("id")
    limit = source.get("limit", 20)

    if not channel:
        logger.warning("Telegram source %s has no channel set", source_name)
        return []

    try:
        entity = await client.get_entity(channel)
        messages = await client.get_messages(entity, limit=limit)
    except Exception as exc:
        logger.warning("Telegram fetch error for %s: %s", channel, exc)
        return []

    articles: List[RawArticle] = []
    for msg in messages:
        if not msg.text:
            continue

        # Use message ID as unique URL-like identifier
        msg_url = f"https://t.me/{channel.lstrip('@')}/{msg.id}"
        title = _first_line(msg.text)
        body = msg.text

        image_url: Optional[str] = None
        # Telethon photo objects are downloaded separately if needed; we store None here
        # and let the image processor handle it via the message photo attribute stored separately

        articles.append(RawArticle(
            url=msg_url,
            title=title,
            body=body,
            image_url=image_url,
            source_name=source_name,
            source_id=source_id,
        ))

    logger.info("Telegram %s: fetched %d messages", channel, len(articles))
    return articles


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return text[:200]
