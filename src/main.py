import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from telegram.error import NetworkError

# Load .env before anything else
load_dotenv()

from src.db.models import init_db
from src.bot.commands import build_application
from src.scheduler import create_scheduler, set_telethon_client
from src.utils.import_sources import import_sources_from_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Avoid logging full Bot API URLs (they contain the bot token in the path).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def load_settings() -> dict:
    settings_path = Path(os.getenv("CONFIG_DIR", "config")) / "settings.yml"
    if settings_path.exists():
        with open(settings_path) as f:
            return yaml.safe_load(f) or {}
    return {}


async def start_telethon():
    """
    Start Telethon client only if:
    - API credentials are set in .env
    - A session file already exists (created via the auth script)

    Without an existing session, Telethon would ask for a phone number
    interactively, which is impossible inside Docker.
    Run the one-time auth script from README to create the session first.
    """
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")

    if not api_id or not api_hash:
        logger.info(
            "TELEGRAM_API_ID/HASH not set — Telethon disabled: "
            "cannot read other Telegram channels as news sources. "
            "The control bot and publishing to your channel still work."
        )
        return None

    session_path = Path(os.getenv("DATA_DIR", "data")) / "telethon_session"
    session_file = session_path.with_suffix(".session")

    if not session_file.exists():
        logger.warning(
            "Telethon session not found at %s. "
            "Run the one-time auth script from README.md to enable Telegram sources.",
            session_file,
        )
        return None

    try:
        from telethon import TelegramClient

        client = TelegramClient(str(session_path), int(api_id), api_hash)
        # connect=True but no_updates=False; won't prompt for phone — session already exists
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Telethon session exists but is not authorized. Re-run auth script.")
            await client.disconnect()
            return None
        logger.info("Telethon client started.")
        set_telethon_client(client)
        return client
    except Exception as exc:
        logger.warning("Failed to start Telethon: %s", exc)
        return None


async def main() -> None:
    admin_raw = os.environ.get("ADMIN_TELEGRAM_ID", "").strip()
    if not admin_raw or admin_raw == "0":
        logger.warning(
            "ADMIN_TELEGRAM_ID is missing or 0 — /start will show your user id; "
            "set it in .env to your numeric Telegram id and restart, then other commands work."
        )

    settings = load_settings()
    interval = settings.get("scheduler", {}).get("interval_minutes", 30)

    logger.info("Initializing database…")
    await init_db()
    await import_sources_from_config()

    telethon_client = await start_telethon()

    logger.info("Starting scheduler (every %d minutes)…", interval)
    scheduler = create_scheduler(interval_minutes=interval)
    scheduler.start()

    logger.info(
        "Configured admin Telegram user id: %s",
        os.environ.get("ADMIN_TELEGRAM_ID", "NOT SET"),
    )
    logger.info("Starting Telegram bot…")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    max_attempts = max(1, int(os.environ.get("TELEGRAM_STARTUP_RETRIES", "5")))

    for attempt in range(1, max_attempts + 1):
        app = build_application(token)
        try:
            async with app:
                await app.start()
                await app.bot.delete_webhook(drop_pending_updates=True)
                # Short polling (timeout=0) works better through HTTP proxies than long poll.
                default_poll_timeout = (
                    "0" if os.environ.get("TELEGRAM_PROXY_URL", "").strip() else "10"
                )
                poll_timeout = int(
                    os.environ.get("TELEGRAM_GET_UPDATES_TIMEOUT", default_poll_timeout)
                )
                poll_interval = float(os.environ.get("TELEGRAM_POLL_INTERVAL", "1"))
                await app.updater.start_polling(
                    drop_pending_updates=True,
                    timeout=poll_timeout,
                    poll_interval=poll_interval,
                )
                logger.info(
                    "Bot is polling (getUpdates timeout=%ss). Press Ctrl+C to stop.",
                    poll_timeout,
                )
                try:
                    probe = await app.bot.get_updates(timeout=0, limit=1)
                    logger.info("getUpdates probe OK (pending in queue: %d)", len(probe))
                except Exception as exc:
                    logger.error(
                        "getUpdates probe failed — bot may not receive your messages: %s",
                        exc,
                    )
                from src.scheduler import run_job

                asyncio.create_task(run_job())

                try:
                    await asyncio.Event().wait()  # Block forever
                except (KeyboardInterrupt, SystemExit):
                    pass
                finally:
                    await app.updater.stop()
                    await app.stop()
                    scheduler.shutdown()
                    if telethon_client:
                        await telethon_client.disconnect()
            break
        except NetworkError as exc:
            if attempt >= max_attempts:
                logger.error(
                    "Telegram API unreachable after %d attempts (%s). "
                    "Check outbound HTTPS to api.telegram.org, DNS, and firewall.",
                    max_attempts,
                    exc,
                )
                scheduler.shutdown()
                if telethon_client:
                    await telethon_client.disconnect()
                raise
            wait_s = min(60.0, 5.0 * attempt)
            logger.warning(
                "Telegram startup failed: %s — retry %d/%d in %.0fs…",
                exc,
                attempt,
                max_attempts,
                wait_s,
            )
            await asyncio.sleep(wait_s)


if __name__ == "__main__":
    asyncio.run(main())
