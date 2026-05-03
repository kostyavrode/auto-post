import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.db.models import get_db
from src.telegram_http import build_telegram_http_request
from src.processor.dedup import (
    get_pending_posts,
    is_posting_enabled,
    set_posting_enabled,
)

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
EXAMPLES_DIR = Path(os.getenv("EXAMPLES_DIR", "examples"))


def admin_only(func):
    """Decorator: only allow the admin user to run this command."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user and update.effective_user.id != ADMIN_ID:
            await update.effective_message.reply_text("Access denied.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ─────────────────────────── /start ────────────────────────────

_START_HELP = (
    "Auto News Poster bot.\n\n"
    "Sources:\n"
    "/add_source <url> [name] — add RSS or website\n"
    "/add_tg <@channel> [name] — add Telegram channel source\n"
    "/list_sources — list all sources\n"
    "/del_source <id> — remove source by ID\n"
    "/toggle_source <id> — enable/disable source\n\n"
    "Examples:\n"
    "/upload_example — upload a post style example\n"
    "/list_examples — show loaded examples\n"
    "/del_example <filename> — delete an example\n\n"
    "Control:\n"
    "/run_now — fetch news and publish right now\n"
    "/retry_failed — retry failed posts (keep text)\n"
    "/reset_posts [all] — reset failed posts with full article text\n"
    "/regenerate — re-generate text for pending posts via AI\n"
    "/pause — pause auto-posting\n"
    "/resume — resume auto-posting\n"
    "/status — statistics\n"
    "/queue — pending posts\n"
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start and /help: always reply (so misconfigured ADMIN_TELEGRAM_ID is obvious).
    Full command list only for the configured admin.
    """
    msg = update.effective_message
    if not msg:
        return
    uid = update.effective_user.id if update.effective_user else None

    if ADMIN_ID == 0:
        await msg.reply_text(
            "ADMIN_TELEGRAM_ID is not set in .env.\n\n"
            f"Your Telegram user id: {uid}\n"
            "Add this number as ADMIN_TELEGRAM_ID, restart the container, then use /start again."
        )
        return

    if uid != ADMIN_ID:
        await msg.reply_text(
            "This bot is restricted to the configured admin only.\n\n"
            f"Your Telegram user id: {uid}\n"
            "If this is your server, set ADMIN_TELEGRAM_ID in .env to this number and restart."
        )
        return

    await msg.reply_text(_START_HELP)


# ─────────────────────────── Sources ────────────────────────────

@admin_only
async def cmd_add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /add_source <url> [name]")
        return

    url = args[0]
    name = " ".join(args[1:]) if len(args) > 1 else url
    src_type = "rss" if _looks_like_rss(url) else "scraper"

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sources (name, type, url) VALUES (?, ?, ?)",
            (name, src_type, url),
        )
        await db.commit()

    await update.effective_message.reply_text(
        f"Source added: {name}\nType: {src_type}\nURL: {url}"
    )


@admin_only
async def cmd_add_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.effective_message.reply_text("Usage: /add_tg <@channel> [name]")
        return

    channel = args[0]
    name = " ".join(args[1:]) if len(args) > 1 else channel

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sources (name, type, channel) VALUES (?, 'telegram', ?)",
            (name, channel),
        )
        await db.commit()

    await update.effective_message.reply_text(f"Telegram source added: {name} ({channel})")


@admin_only
async def cmd_list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with get_db() as db:
        async with db.execute("SELECT id, name, type, url, channel, enabled FROM sources") as cur:
            rows = await cur.fetchall()

    if not rows:
        await update.effective_message.reply_text("No sources configured.")
        return

    lines = []
    for r in rows:
        status = "✅" if r["enabled"] else "❌"
        target = r["url"] or r["channel"] or "—"
        lines.append(f"{status} [{r['id']}] {r['name']} ({r['type']})\n    {target}")

    await update.effective_message.reply_text("\n\n".join(lines))


@admin_only
async def cmd_del_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Usage: /del_source <id>")
        return
    source_id = int(context.args[0])
    async with get_db() as db:
        await db.execute("DELETE FROM sources WHERE id=?", (source_id,))
        await db.commit()
    await update.effective_message.reply_text(f"Source {source_id} deleted.")


@admin_only
async def cmd_toggle_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Usage: /toggle_source <id>")
        return
    source_id = int(context.args[0])
    async with get_db() as db:
        async with db.execute("SELECT enabled FROM sources WHERE id=?", (source_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.effective_message.reply_text(f"Source {source_id} not found.")
            return
        new_val = 0 if row["enabled"] else 1
        await db.execute("UPDATE sources SET enabled=? WHERE id=?", (new_val, source_id))
        await db.commit()
    state = "enabled" if new_val else "disabled"
    await update.effective_message.reply_text(f"Source {source_id} is now {state}.")


# ─────────────────────────── Examples ────────────────────────────

# We track users who called /upload_example awaiting their next message
_awaiting_example: set = set()


@admin_only
async def cmd_upload_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _awaiting_example.add(update.effective_user.id)
    await update.effective_message.reply_text(
        "Send your example post text as the next message (plain text, no commands)."
    )


async def handle_example_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id not in _awaiting_example:
        return
    _awaiting_example.discard(user_id)

    text = (update.effective_message.text if update.effective_message else "") or ""
    if not text.strip():
        await update.effective_message.reply_text("Empty text, example not saved.")
        return

    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(EXAMPLES_DIR.glob("example_*.txt"))
    next_num = len(existing) + 1
    filename = f"example_{next_num:03d}.txt"
    (EXAMPLES_DIR / filename).write_text(text, encoding="utf-8")

    await update.effective_message.reply_text(f"Example saved as {filename} ({len(text)} chars).")


@admin_only
async def cmd_list_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(EXAMPLES_DIR.glob("*.txt"))
    if not files:
        await update.effective_message.reply_text("No examples loaded.")
        return
    lines = []
    for f in files:
        size = f.stat().st_size
        preview = f.read_text(encoding="utf-8")[:80].replace("\n", " ")
        lines.append(f"📄 {f.name} ({size}B)\n{preview}...")
    await update.effective_message.reply_text("\n\n".join(lines))


@admin_only
async def cmd_del_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Usage: /del_example <filename>")
        return
    filename = context.args[0]
    path = EXAMPLES_DIR / filename
    if path.exists() and path.suffix == ".txt":
        path.unlink()
        await update.effective_message.reply_text(f"Deleted {filename}.")
    else:
        await update.effective_message.reply_text(f"File not found: {filename}")


# ─────────────────────────── Control ────────────────────────────

@admin_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_posting_enabled(False)
    await update.effective_message.reply_text("Auto-posting paused.")


@admin_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_posting_enabled(True)
    await update.effective_message.reply_text("Auto-posting resumed.")


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enabled = await is_posting_enabled()
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as n FROM articles") as cur:
            total_articles = (await cur.fetchone())["n"]
        async with db.execute(
            "SELECT COUNT(*) as n FROM posts WHERE status='published'"
        ) as cur:
            published = (await cur.fetchone())["n"]
        async with db.execute(
            "SELECT COUNT(*) as n FROM posts WHERE status='pending'"
        ) as cur:
            pending = (await cur.fetchone())["n"]
        async with db.execute(
            "SELECT COUNT(*) as n FROM sources WHERE enabled=1"
        ) as cur:
            active_sources = (await cur.fetchone())["n"]

    status_line = "✅ Running" if enabled else "⏸ Paused"
    await update.effective_message.reply_text(
        f"Status: {status_line}\n"
        f"Active sources: {active_sources}\n"
        f"Articles fetched: {total_articles}\n"
        f"Posts published: {published}\n"
        f"Posts pending: {pending}"
    )


@admin_only
async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    posts = await get_pending_posts(limit=5)
    if not posts:
        await update.effective_message.reply_text("No pending posts.")
        return
    lines = []
    for p in posts:
        preview = (p["generated_text"] or "")[:100].replace("\n", " ")
        lines.append(f"[{p['id']}] {preview}...")
    await update.effective_message.reply_text("Pending posts (first 5):\n\n" + "\n\n".join(lines))


@admin_only
async def cmd_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-generate post text for all pending posts using Deepseek."""
    from src.processor.generator import generate_post

    msg = update.effective_message
    await msg.reply_text("Re-generating posts with AI, please wait…")

    async with get_db() as db:
        async with db.execute(
            """SELECT p.id, a.title, a.body, a.url
               FROM posts p JOIN articles a ON a.id = p.article_id
               WHERE p.status = 'pending'"""
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await msg.reply_text("No pending posts to regenerate.")
        return

    ok, fail = 0, 0
    for row in rows:
        try:
            new_text = await generate_post(
                title=row["title"] or "",
                body=row["body"] or "",
                source_url=row["url"] or "",
            )
            async with get_db() as db:
                await db.execute(
                    "UPDATE posts SET generated_text=? WHERE id=?",
                    (new_text, row["id"]),
                )
                await db.commit()
            ok += 1
        except Exception as exc:
            logger.warning("Regeneration failed for post %s: %s", row["id"], exc)
            fail += 1

    await msg.reply_text(
        f"Done. Regenerated: {ok}, failed: {fail}.\n"
        "Use /run_now to publish."
    )


@admin_only
async def cmd_retry_failed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset failed posts back to pending (keep existing generated text)."""
    msg = update.effective_message
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as n FROM posts WHERE status='failed'"
        ) as cur:
            count = (await cur.fetchone())["n"]

        if count == 0:
            await msg.reply_text("No failed posts to retry.")
            return

        await db.execute("UPDATE posts SET status='pending', error=NULL WHERE status='failed'")
        await db.commit()

    await msg.reply_text(
        f"Reset {count} failed post(s) to pending.\n"
        "Use /run_now to publish them."
    )


@admin_only
async def cmd_reset_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Reset ALL non-published posts (failed + pending) to pending,
    and rebuild their text from the original article body.
    Useful when posts got truncated or AI was unavailable.

    Usage:
      /reset_posts          — reset failed posts only
      /reset_posts all      — reset failed + already-pending posts too
    """
    msg = update.effective_message
    args = context.args or []
    include_pending = "all" in args

    statuses = ("'failed'", "'pending'") if include_pending else ("'failed'",)
    status_filter = f"status IN ({','.join(statuses)})"

    async with get_db() as db:
        async with db.execute(
            f"SELECT COUNT(*) as n FROM posts WHERE {status_filter}"
        ) as cur:
            count = (await cur.fetchone())["n"]

        if count == 0:
            await msg.reply_text("No posts to reset.")
            return

        # Rebuild generated_text from article: full title + body + source url
        await db.execute(f"""
            UPDATE posts SET
                status = 'pending',
                error  = NULL,
                generated_text = (
                    SELECT
                        '<b>' || COALESCE(a.title, '') || '</b>'
                        || char(10) || char(10)
                        || COALESCE(a.body, '')
                        || char(10) || char(10)
                        || COALESCE(a.url, '')
                    FROM articles a WHERE a.id = posts.article_id
                )
            WHERE {status_filter}
        """)
        await db.commit()

    scope = "failed + pending" if include_pending else "failed"
    await msg.reply_text(
        f"Reset {count} post(s) ({scope}) with full article text.\n"
        "Use /run_now to publish, or /regenerate to re-process with AI first."
    )


@admin_only
async def cmd_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a full fetch + publish cycle right now."""
    from src.scheduler import run_job

    msg = update.effective_message
    await msg.reply_text("Starting fetch cycle now, please wait…")
    try:
        await run_job()
        await msg.reply_text("Cycle complete. Use /status or /queue to see results.")
    except Exception as exc:
        logger.error("run_now error: %s", exc)
        await msg.reply_text(f"Error during cycle: {exc}")


# ─────────────────────────── App builder ────────────────────────

def build_application(token: str) -> Application:
    request = build_telegram_http_request()
    app = Application.builder().token(token).request(request).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add_source", cmd_add_source))
    app.add_handler(CommandHandler("add_tg", cmd_add_tg))
    app.add_handler(CommandHandler("list_sources", cmd_list_sources))
    app.add_handler(CommandHandler("del_source", cmd_del_source))
    app.add_handler(CommandHandler("toggle_source", cmd_toggle_source))
    app.add_handler(CommandHandler("upload_example", cmd_upload_example))
    app.add_handler(CommandHandler("list_examples", cmd_list_examples))
    app.add_handler(CommandHandler("del_example", cmd_del_example))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("run_now", cmd_run_now))
    app.add_handler(CommandHandler("retry_failed", cmd_retry_failed))
    app.add_handler(CommandHandler("reset_posts", cmd_reset_posts))
    app.add_handler(CommandHandler("regenerate", cmd_regenerate))

    # Catch plain text messages for example uploads
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_example_text)
    )

    return app


# ─────────────────────────── Helpers ────────────────────────────

def _looks_like_rss(url: str) -> bool:
    rss_hints = ("rss", "feed", "atom", ".xml")
    return any(h in url.lower() for h in rss_hints)
