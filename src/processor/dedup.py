import logging
from typing import Optional

import aiosqlite

from src.db.models import get_db
from src.fetchers.rss import RawArticle

logger = logging.getLogger(__name__)


async def is_duplicate(url: str) -> bool:
    """Return True if the article URL was already stored."""
    async with await get_db() as db:
        async with db.execute(
            "SELECT id FROM articles WHERE url = ?", (url,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def save_article(article: RawArticle, lang: Optional[str] = None) -> Optional[int]:
    """
    Insert article into DB. Returns new row id, or None if duplicate.
    """
    async with await get_db() as db:
        try:
            async with db.execute(
                """
                INSERT INTO articles (source_id, url, title, body, image_url, lang_detected)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    article.source_id,
                    article.url,
                    article.title,
                    article.body,
                    article.image_url,
                    lang,
                ),
            ) as cursor:
                article_id = cursor.lastrowid
            await db.commit()
            return article_id
        except aiosqlite.IntegrityError:
            logger.debug("Duplicate article skipped: %s", article.url)
            return None


async def update_image_path(article_id: int, image_path: str) -> None:
    async with await get_db() as db:
        await db.execute(
            "UPDATE articles SET image_path = ? WHERE id = ?",
            (image_path, article_id),
        )
        await db.commit()


async def create_pending_post(article_id: int, generated_text: str) -> int:
    async with await get_db() as db:
        async with db.execute(
            "INSERT INTO posts (article_id, generated_text, status) VALUES (?, ?, 'pending')",
            (article_id, generated_text),
        ) as cursor:
            post_id = cursor.lastrowid
        await db.commit()
        return post_id


async def mark_post_published(post_id: int) -> None:
    async with await get_db() as db:
        await db.execute(
            "UPDATE posts SET status='published', published_at=datetime('now') WHERE id=?",
            (post_id,),
        )
        await db.commit()


async def mark_post_failed(post_id: int, error: str) -> None:
    async with await get_db() as db:
        await db.execute(
            "UPDATE posts SET status='failed', error=? WHERE id=?",
            (error, post_id),
        )
        await db.commit()


async def get_pending_posts(limit: int = 10) -> list:
    async with await get_db() as db:
        async with db.execute(
            """
            SELECT p.id, p.generated_text, a.image_path, a.url, a.title
            FROM posts p
            JOIN articles a ON a.id = p.article_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            return await cursor.fetchall()


async def is_posting_enabled() -> bool:
    async with await get_db() as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key='posting_enabled'"
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None and row["value"] == "1"


async def set_posting_enabled(enabled: bool) -> None:
    async with await get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('posting_enabled', ?)",
            ("1" if enabled else "0",),
        )
        await db.commit()
