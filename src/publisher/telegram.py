import logging
import os
from pathlib import Path
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# Telegram hard limits
_CAPTION_LIMIT = 1024
_MESSAGE_LIMIT = 4096


async def publish_post(
    text: str,
    image_path: Optional[str] = None,
    channel_id: str = "",
) -> bool:
    """
    Publish a post to the Telegram channel.

    Strategy:
    - Short text (≤ 1024) + image  → photo with caption
    - Long text  (> 1024) + image  → photo (no caption) + text as separate message
    - No image                     → text message only (up to 4096 chars)

    Returns True on success, False on failure.
    """
    target = channel_id or CHANNEL_ID
    if not target:
        logger.error("TELEGRAM_CHANNEL_ID is not set")
        return False

    bot = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    has_image = bool(image_path and Path(image_path).exists())

    try:
        if has_image:
            if len(text) <= _CAPTION_LIMIT:
                # Short post — photo + caption
                with open(image_path, "rb") as photo:
                    await bot.send_photo(
                        chat_id=target,
                        photo=photo,
                        caption=text,
                        parse_mode=ParseMode.HTML,
                    )
            else:
                # Long post — photo first, then full text as message
                with open(image_path, "rb") as photo:
                    await bot.send_photo(chat_id=target, photo=photo)
                await bot.send_message(
                    chat_id=target,
                    text=text[:_MESSAGE_LIMIT],
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        else:
            await bot.send_message(
                chat_id=target,
                text=text[:_MESSAGE_LIMIT],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )

        logger.info("Published post to %s", target)
        return True

    except TelegramError as exc:
        logger.error("Telegram publish error: %s", exc)
        return False
