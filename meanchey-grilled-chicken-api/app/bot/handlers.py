import logging
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonDefault,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.attendance.tracking import status_on
from app.attendance.workplaces import today
from app.bot.i18n import t
from app.config import get_settings
from app.db import SessionLocal
from app.models import BotPref, Language, User, utcnow
from app.services import telegram_link_service

log = logging.getLogger(__name__)


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


def menu_button(lang: Language) -> MenuButtonWebApp | MenuButtonDefault:
    """The bot's menu button: Open app → MINI_APP_URL (the default button without HTTPS)."""
    url = get_settings().mini_app_url
    if not url.startswith("https://"):
        return MenuButtonDefault()
    return MenuButtonWebApp(text=t(lang, "menu_button"), web_app=WebAppInfo(url=url))


# The Mini App's check screen: it reads the next action from the API (check in or check out).
CHECK_PATH = "/attendance/check"


def check_keyboard(lang: Language, button: str) -> InlineKeyboardMarkup | None:
    """One web_app button to the check screen; None when MINI_APP_URL isn't HTTPS."""
    base = get_settings().mini_app_url
    if not base.startswith("https://"):
        return None
    url = base.rstrip("/") + CHECK_PATH
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, button), web_app=WebAppInfo(url=url))]]
    )


def app_keyboard(lang: Language, *, attendance: bool = False) -> InlineKeyboardMarkup | None:
    """Open app; with `attendance` (tracked employees) also Attendance → the check screen, side
    by side (currently disabled: Open app only). None when MINI_APP_URL isn't HTTPS (Telegram
    only accepts HTTPS Mini App URLs)."""
    url = get_settings().mini_app_url
    if not url.startswith("https://"):
        return None
    row = [InlineKeyboardButton(text=t(lang, "open_app"), web_app=WebAppInfo(url=url))]
    # Attendance button on /start disabled for now (reminders + Home card are the entry points);
    # uncomment to restore.
    # if attendance:
    #     row.append(
    #         InlineKeyboardButton(
    #             text=t(lang, "button_attendance"),
    #             web_app=WebAppInfo(url=url.rstrip("/") + CHECK_PATH),
    #         )
    #     )
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def _is_tracked(telegram_user_id: int) -> bool:
    """A linked Telegram account of an employee tracked today or whose attendance starts later
    (an active staff member or supervisor; not one whose attendance is switched off)."""
    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id, User.is_active)
        )
    if user is None:
        return False
    return status_on(user, today(), user.attendance_periods) in ("tracked", "not_started")


async def _answer(message: Message, text: str, lang: Language, *, attendance: bool = False) -> None:
    keyboard = app_keyboard(lang, attendance=attendance)
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
    async with SessionLocal() as session:
        bound = await telegram_link_service.bind_on_start(
            session, message.from_user.id, message.from_user.username
        )
    lang = await get_language(message.from_user.id)
    name = escape(message.from_user.first_name or "")
    text = t(lang, "start", name=name)
    if bound:
        text = f"{text}\n\n{t(lang, 'start_linked')}"
    # The Attendance button is disabled (app_keyboard), so the tracked-employee lookup is skipped.
    # To restore: uncomment the button and pass attendance=await _is_tracked(message.from_user.id).
    await _answer(message, text, lang)
    await set_chat_menu(message, lang)


async def on_lang(message: Message) -> None:
    if message.from_user is None:
        return
    current = await get_language(message.from_user.id)
    new = Language.EN if current == Language.KM else Language.KM
    await set_language(message.from_user.id, new)
    await _answer(message, t(new, "lang_changed"), new)
    await set_chat_menu(message, new)


async def set_chat_menu(message: Message, lang: Language) -> None:
    """The menu button of this chat, labelled in the user's language. Best effort."""
    if message.bot is None:
        return
    try:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id, menu_button=menu_button(lang)
        )
    except Exception:  # an old client or a network hiccup must not break the command
        log.warning("could not set the chat menu button", exc_info=True)


def create_router() -> Router:
    """A fresh router per dispatcher (aiogram routers can only have one parent)."""
    router = Router(name="bot")
    router.message.register(on_start, CommandStart())
    router.message.register(on_lang, Command("lang"))
    return router
