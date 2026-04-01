import logging
from dataclasses import dataclass, field
from typing import List, Optional

import feedparser
import httpx

logger = logging.getLogger(__name__)


@dataclass
class RawArticle:
    url: str
    title: str
    body: str
    image_url: Optional[str] = None
    source_name: str = ""
    source_id: Optional[int] = None


async def fetch_rss(source: dict) -> List[RawArticle]:
    """Fetch articles from an RSS feed."""
    url = source["url"]
    source_name = source.get("name", url)
    source_id = source.get("id")

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "NewsBot/1.0"})
            response.raise_for_status()
            content = response.text
    except Exception as exc:
        logger.warning("RSS fetch error for %s: %s", url, exc)
        return []

    feed = feedparser.parse(content)
    articles: List[RawArticle] = []

    for entry in feed.entries:
        article_url = entry.get("link", "")
        if not article_url:
            continue

        title = entry.get("title", "").strip()
        body = _extract_body(entry)
        image_url = _extract_image(entry)

        articles.append(RawArticle(
            url=article_url,
            title=title,
            body=body,
            image_url=image_url,
            source_name=source_name,
            source_id=source_id,
        ))

    logger.info("RSS %s: fetched %d articles", source_name, len(articles))
    return articles


def _extract_body(entry) -> str:
    """Try to extract article body text from RSS entry."""
    if "content" in entry and entry.content:
        return entry.content[0].get("value", "")
    if "summary" in entry:
        return entry.summary
    return ""


def _extract_image(entry) -> Optional[str]:
    """Try to extract image URL from RSS entry."""
    if "media_thumbnail" in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    if "media_content" in entry:
        for media in entry.media_content:
            if media.get("medium") == "image" or media.get("url", "").endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                return media["url"]
    if "enclosures" in entry:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href") or enc.get("url")
    return None
