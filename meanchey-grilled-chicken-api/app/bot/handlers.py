from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.bot.i18n import t
from app.config import get_settings
from app.db import SessionLocal
from app.models import BotPref, Language, User, utcnow
from app.services import telegram_link_service


async def get_language(telegram_user_id: int) -> Language:
    async with SessionLocal() as session:
        lang = await session.scalar(
            select(User.language).where(User.telegram_user_id == telegram_user_id, User.is_active)
        )
        if lang is not None:
            return lang
        pref = await session.get(BotPref, telegram_user_id)
        return pref.language if pref else Language.KM


async def set_language(telegram_user_id: int, lang: Language) -> None:
    async with SessionLocal() as session:
        await session.execute(
            pg_insert(BotPref)
            .values(telegram_user_id=telegram_user_id, language=lang)
            .on_conflict_do_update(
                index_elements=[BotPref.telegram_user_id],
                set_={"language": lang, "updated_at": utcnow()},
            )
        )
        # Keep a linked account's app language in sync with the bot.
        await session.execute(
            update(User)
            .where(User.telegram_user_id == telegram_user_id, User.is_active)
            .values(language=lang, updated_at=utcnow())
        )
        await session.commit()


def app_keyboard(lang: Language) -> InlineKeyboardMarkup | None:
    url = get_settings().mini_app_url
    # Telegram only accepts HTTPS Mini App URLs.
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "open_app"), web_app=WebAppInfo(url=url))]
        ]
    )


async def _answer(message: Message, text: str, lang: Language) -> None:
    keyboard = app_keyboard(lang)
    if keyboard is None:
        text = f"{text}\n\n{t(lang, 'app_unavailable')}"
    await message.answer(text, reply_markup=keyboard)


async def on_link(message: Message, raw_token: str) -> None:
    """`/start link_<token>`: bind this Telegram account to the account that created the link."""
    assert message.from_user is not None
    async with SessionLocal() as session:
        linked_lang = await telegram_link_service.consume(session, raw_token, message.from_user.id)
    if linked_lang is None:
        # Same reply for unknown, expired, used or already-bound: nothing to learn from it.
        lang = await get_language(message.from_user.id)
        await message.answer(t(lang, "link_invalid"))
        return
    await message.answer(t(linked_lang, "link_done"))


async def on_start(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    args = (command.args or "").strip()
    if args.startswith(telegram_link_service.START_PREFIX):
        await on_link(message, args.removeprefix(telegram_link_service.START_PREFIX))
        return
    lang = await get_language(message.from_user.id)
    name = escape(message.from_user.first_name or "")
    await _answer(message, t(lang, "start", name=name), lang)


async def on_lang(message: Message) -> None:
    if message.from_user is None:
        return
    current = await get_language(message.from_user.id)
    new = Language.EN if current == Language.KM else Language.KM
    await set_language(message.from_user.id, new)
    await _answer(message, t(new, "lang_changed"), new)


def create_router() -> Router:
    """A fresh router per dispatcher (aiogram routers can only have one parent)."""
    router = Router(name="bot")
    router.message.register(on_start, CommandStart())
    router.message.register(on_lang, Command("lang"))
    return router
