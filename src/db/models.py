import aiosqlite
import os
from pathlib import Path

DB_PATH = Path(os.getenv("DATA_DIR", "data")) / "db.sqlite3"

CREATE_TABLES = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    type        TEXT    NOT NULL CHECK(type IN ('rss', 'scraper', 'telegram')),
    url         TEXT,
    channel     TEXT,
    config_json TEXT    DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    url          TEXT    UNIQUE,
    title        TEXT,
    body         TEXT,
    image_url    TEXT,
    image_path   TEXT,
    lang_detected TEXT,
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id   INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    generated_text TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending'
                         CHECK(status IN ('pending', 'published', 'failed', 'skipped')),
    error        TEXT,
    published_at TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO settings (key, value) VALUES ('posting_enabled', '1');
"""


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES)
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db
