"""Bot and dispatcher construction, shared by webhook mode (FastAPI) and polling mode."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.handlers import create_router
from app.config import get_settings

BOT_COMMANDS = [
    BotCommand(command="start", description="Open the app / បើកកម្មវិធី"),
    BotCommand(command="lang", description="Switch language / ប្តូរភាសា"),
]


def create_bot(session: BaseSession | None = None) -> Bot:
    return Bot(
        get_settings().telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """The single place where bot handlers are registered."""
    dp = Dispatcher()
    dp.include_router(create_router())
    return dp
