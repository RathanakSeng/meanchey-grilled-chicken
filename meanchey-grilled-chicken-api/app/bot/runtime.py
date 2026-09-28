import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher

from app.bot.setup import create_bot, create_dispatcher
from app.config import Settings

log = logging.getLogger(__name__)


@dataclass
class TelegramRuntime:
    """The bot + dispatcher living inside the API process (webhook mode). Stored on app.state."""

    bot: Bot
    dp: Dispatcher
    secret: str

    async def close(self) -> None:
        await self.bot.session.close()


def create_runtime(settings: Settings) -> TelegramRuntime | None:
    """A runtime in webhook mode with a token; None otherwise (the webhook endpoint then 404s)."""
    if not settings.telegram_bot_token:
        if settings.bot_mode != "off":
            log.warning("TELEGRAM_BOT_TOKEN is not set; the Telegram bot is disabled")
        return None
    if settings.bot_mode != "webhook":
        return None
    return TelegramRuntime(
        bot=create_bot(), dp=create_dispatcher(), secret=settings.telegram_webhook_secret
    )
