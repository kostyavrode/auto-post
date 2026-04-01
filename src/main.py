import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

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
        logger.info("TELEGRAM_API_ID/HASH not set — Telegram channel sources disabled.")
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
    settings = load_settings()
    interval = settings.get("scheduler", {}).get("interval_minutes", 30)

    logger.info("Initializing database…")
    await init_db()
    await import_sources_from_config()

    telethon_client = await start_telethon()

    logger.info("Starting scheduler (every %d minutes)…", interval)
    scheduler = create_scheduler(interval_minutes=interval)
    scheduler.start()

    # Run the first fetch immediately on startup
    from src.scheduler import run_job
    asyncio.create_task(run_job())

    logger.info("Starting Telegram bot…")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = build_application(token)

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is polling. Press Ctrl+C to stop.")

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


if __name__ == "__main__":
    asyncio.run(main())
