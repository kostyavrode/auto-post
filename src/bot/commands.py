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
            await update.message.reply_text("Access denied.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper


# ─────────────────────────── /start ────────────────────────────

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Auto News Poster bot.\n\n"
        "Commands:\n"
        "/add_source <url> [name] — add RSS or web source\n"
        "/add_tg <@channel> [name] — add Telegram channel source\n"
        "/list_sources — list all sources\n"
        "/del_source <id> — remove source by ID\n"
        "/toggle_source <id> — enable/disable source\n"
        "/upload_example — reply to this, then send your example post text\n"
        "/list_examples — show loaded examples\n"
        "/del_example <filename> — delete an example\n"
        "/pause — pause auto-posting\n"
        "/resume — resume auto-posting\n"
        "/status — show statistics\n"
        "/queue — show pending posts count\n"
    )


# ─────────────────────────── Sources ────────────────────────────

@admin_only
async def cmd_add_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /add_source <url> [name]")
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

    await update.message.reply_text(
        f"Source added: {name}\nType: {src_type}\nURL: {url}"
    )


@admin_only
async def cmd_add_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /add_tg <@channel> [name]")
        return

    channel = args[0]
    name = " ".join(args[1:]) if len(args) > 1 else channel

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sources (name, type, channel) VALUES (?, 'telegram', ?)",
            (name, channel),
        )
        await db.commit()

    await update.message.reply_text(f"Telegram source added: {name} ({channel})")


@admin_only
async def cmd_list_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with get_db() as db:
        async with db.execute("SELECT id, name, type, url, channel, enabled FROM sources") as cur:
            rows = await cur.fetchall()

    if not rows:
        await update.message.reply_text("No sources configured.")
        return

    lines = []
    for r in rows:
        status = "✅" if r["enabled"] else "❌"
        target = r["url"] or r["channel"] or "—"
        lines.append(f"{status} [{r['id']}] {r['name']} ({r['type']})\n    {target}")

    await update.message.reply_text("\n\n".join(lines))


@admin_only
async def cmd_del_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /del_source <id>")
        return
    source_id = int(context.args[0])
    async with get_db() as db:
        await db.execute("DELETE FROM sources WHERE id=?", (source_id,))
        await db.commit()
    await update.message.reply_text(f"Source {source_id} deleted.")


@admin_only
async def cmd_toggle_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /toggle_source <id>")
        return
    source_id = int(context.args[0])
    async with get_db() as db:
        async with db.execute("SELECT enabled FROM sources WHERE id=?", (source_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            await update.message.reply_text(f"Source {source_id} not found.")
            return
        new_val = 0 if row["enabled"] else 1
        await db.execute("UPDATE sources SET enabled=? WHERE id=?", (new_val, source_id))
        await db.commit()
    state = "enabled" if new_val else "disabled"
    await update.message.reply_text(f"Source {source_id} is now {state}.")


# ─────────────────────────── Examples ────────────────────────────

# We track users who called /upload_example awaiting their next message
_awaiting_example: set = set()


@admin_only
async def cmd_upload_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _awaiting_example.add(update.effective_user.id)
    await update.message.reply_text(
        "Send your example post text as the next message (plain text, no commands)."
    )


async def handle_example_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else 0
    if user_id not in _awaiting_example:
        return
    _awaiting_example.discard(user_id)

    text = update.message.text or ""
    if not text.strip():
        await update.message.reply_text("Empty text, example not saved.")
        return

    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(EXAMPLES_DIR.glob("example_*.txt"))
    next_num = len(existing) + 1
    filename = f"example_{next_num:03d}.txt"
    (EXAMPLES_DIR / filename).write_text(text, encoding="utf-8")

    await update.message.reply_text(f"Example saved as {filename} ({len(text)} chars).")


@admin_only
async def cmd_list_examples(update: Update, context: ContextTypes.DEFAULT_TYPE):
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(EXAMPLES_DIR.glob("*.txt"))
    if not files:
        await update.message.reply_text("No examples loaded.")
        return
    lines = []
    for f in files:
        size = f.stat().st_size
        preview = f.read_text(encoding="utf-8")[:80].replace("\n", " ")
        lines.append(f"📄 {f.name} ({size}B)\n{preview}...")
    await update.message.reply_text("\n\n".join(lines))


@admin_only
async def cmd_del_example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /del_example <filename>")
        return
    filename = context.args[0]
    path = EXAMPLES_DIR / filename
    if path.exists() and path.suffix == ".txt":
        path.unlink()
        await update.message.reply_text(f"Deleted {filename}.")
    else:
        await update.message.reply_text(f"File not found: {filename}")


# ─────────────────────────── Control ────────────────────────────

@admin_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_posting_enabled(False)
    await update.message.reply_text("Auto-posting paused.")


@admin_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_posting_enabled(True)
    await update.message.reply_text("Auto-posting resumed.")


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
    await update.message.reply_text(
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
        await update.message.reply_text("No pending posts.")
        return
    lines = []
    for p in posts:
        preview = (p["generated_text"] or "")[:100].replace("\n", " ")
        lines.append(f"[{p['id']}] {preview}...")
    await update.message.reply_text(f"Pending posts (first 5):\n\n" + "\n\n".join(lines))


# ─────────────────────────── App builder ────────────────────────

def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()

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

    # Catch plain text messages for example uploads
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_example_text)
    )

    return app


# ─────────────────────────── Helpers ────────────────────────────

def _looks_like_rss(url: str) -> bool:
    rss_hints = ("rss", "feed", "atom", ".xml")
    return any(h in url.lower() for h in rss_hints)
