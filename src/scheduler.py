import asyncio
import json
import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.db.models import get_db
from src.fetchers.rss import fetch_rss
from src.fetchers.scraper import fetch_scraper
from src.fetchers.tg_source import fetch_telegram
from src.processor.dedup import (
    create_pending_post,
    get_pending_posts,
    is_duplicate,
    is_posting_enabled,
    mark_post_failed,
    mark_post_published,
    save_article,
    update_image_path,
)
from src.processor.generator import generate_post
from src.processor.image import download_image
from src.processor.translator import detect_language, translate_text
from src.publisher.telegram import publish_post

logger = logging.getLogger(__name__)

# Prevents scheduler and /run_now from running concurrently
_job_lock = asyncio.Lock()

TARGET_LANG = os.environ.get("TARGET_LANGUAGE", "ru")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "5"))
DELAY_BETWEEN_POSTS = int(os.environ.get("DELAY_BETWEEN_POSTS", "10"))

_telethon_client = None


def set_telethon_client(client) -> None:
    global _telethon_client
    _telethon_client = client


async def _load_sources() -> list:
    async with get_db() as db:
        async with db.execute(
            "SELECT id, name, type, url, channel, config_json, enabled FROM sources WHERE enabled=1"
        ) as cur:
            return await cur.fetchall()


async def fetch_all_sources() -> None:
    """Fetch new articles from all enabled sources and queue them for posting."""
    sources = await _load_sources()
    if not sources:
        logger.info("No enabled sources, skipping fetch.")
        return

    for source in sources:
        source_dict = dict(source)
        # Merge extra config stored as JSON (selectors, limit, etc.)
        extra = json.loads(source_dict.get("config_json") or "{}")
        source_dict.update(extra)
        src_type = source_dict["type"]

        try:
            if src_type == "rss":
                articles = await fetch_rss(source_dict)
            elif src_type == "scraper":
                articles = await fetch_scraper(source_dict)
            elif src_type == "telegram":
                if _telethon_client is None:
                    logger.warning("Telethon client not set, skipping TG source: %s", source_dict["name"])
                    continue
                articles = await fetch_telegram(source_dict, _telethon_client)
            else:
                logger.warning("Unknown source type: %s", src_type)
                continue
        except Exception as exc:
            logger.error("Error fetching source %s: %s", source_dict["name"], exc)
            continue

        for article in articles:
            if await is_duplicate(article.url):
                continue

            # Detect language and translate if needed
            lang = detect_language((article.title or "") + " " + (article.body or ""))
            translated_title = article.title
            translated_body = article.body

            if lang != TARGET_LANG and lang != "unknown":
                try:
                    translated_title = await translate_text(article.title, TARGET_LANG, LLM_MODEL)
                    translated_body = await translate_text(article.body, TARGET_LANG, LLM_MODEL)
                except Exception as exc:
                    logger.warning("Translation failed for %s: %s", article.url, exc)

            article_id = await save_article(article, lang=lang)
            if article_id is None:
                continue  # race condition duplicate

            # Download image
            image_path: Optional[str] = None
            if article.image_url:
                image_path = await download_image(article.image_url)
                if image_path:
                    await update_image_path(article_id, image_path)

            # Generate post
            try:
                post_text = await generate_post(
                    title=translated_title,
                    body=translated_body,
                    source_url=article.url,
                    model=LLM_MODEL,
                )
            except Exception as exc:
                logger.error("Generation failed for %s: %s", article.url, exc)
                # Fallback: use full article body (Telegram message limit is 4096 chars)
                post_text = f"<b>{translated_title}</b>\n\n{translated_body}\n\n{article.url}"

            await create_pending_post(article_id, post_text)
            logger.info("Queued article: %s", article.url)


async def publish_pending() -> None:
    """Publish queued posts to the Telegram channel."""
    if not await is_posting_enabled():
        logger.info("Posting is paused, skipping publish.")
        return

    posts = await get_pending_posts(limit=MAX_PER_RUN)
    if not posts:
        logger.info("No pending posts to publish.")
        return

    for post in posts:
        success = await publish_post(
            text=post["generated_text"] or "",
            image_path=post["image_path"],
        )
        if success:
            await mark_post_published(post["id"])
        else:
            await mark_post_failed(post["id"], "publish_failed")

        await asyncio.sleep(DELAY_BETWEEN_POSTS)


async def run_job() -> None:
    """Main scheduled job: fetch new articles, then publish pending posts."""
    if _job_lock.locked():
        logger.info("Job already running, skipping this trigger.")
        return
    async with _job_lock:
        logger.info("Starting scheduled job…")
        await fetch_all_sources()
        await publish_pending()
        logger.info("Scheduled job complete.")


def create_scheduler(interval_minutes: int = 30) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_job,
        trigger="interval",
        minutes=interval_minutes,
        id="news_job",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
