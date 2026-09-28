"""Bot command line.

    python -m app.bot                   # polling mode (BOT_MODE=polling): delete webhook, then poll
    python -m app.bot webhook set       # register the webhook from settings
    python -m app.bot webhook delete    # remove it (add --drop-pending to discard queued updates)
    python -m app.bot webhook info      # show what Telegram has registered

In webhook mode (the default) there is no bot process: the API serves /api/telegram/webhook.
"""

import argparse
import asyncio
import logging
import sys

from app.bot.registration import delete_webhook, set_webhook, webhook_info
from app.bot.setup import BOT_COMMANDS, create_bot, create_dispatcher
from app.config import get_settings
from app.db import SessionLocal, engine

log = logging.getLogger("app.bot")


async def run_polling() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN is not set; bot is disabled")
        return 0
    if settings.bot_mode != "polling":
        log.error(
            "BOT_MODE is %r. Polling only runs with BOT_MODE=polling "
            "(in webhook mode the API receives updates itself).",
            settings.bot_mode,
        )
        return 1

    bot = create_bot()
    dp = create_dispatcher()
    try:
        info = await webhook_info(bot)
        if info.url:
            log.warning(
                "A webhook is registered (%s); deleting it so polling can work. If the API "
                "still runs with BOT_MODE=webhook it will re-register it on restart - set "
                "BOT_MODE=polling in .env for the whole stack.",
                info.url,
            )
        async with SessionLocal() as session:
            await delete_webhook(bot, session)
            await session.commit()
        await bot.set_my_commands(BOT_COMMANDS)
        log.info("bot started (polling)")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
    return 0


async def run_webhook_command(action: str, drop_pending: bool) -> int:
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set")
        return 1
    bot = create_bot()
    try:
        if action == "info":
            info = await webhook_info(bot)
            print(f"url:                  {info.url or '(none)'}")
            print(f"pending_update_count: {info.pending_update_count}")
            print(f"allowed_updates:      {info.allowed_updates or '(all)'}")
            print(f"last_error_date:      {info.last_error_date or '-'}")
            print(f"last_error_message:   {info.last_error_message or '-'}")
            return 0
        async with SessionLocal() as session:
            if action == "set":
                await set_webhook(bot, create_dispatcher(), session)
                print(f"webhook set: {settings.telegram_webhook_url}")
            else:
                await delete_webhook(bot, session, drop_pending=drop_pending)
                print("webhook deleted")
            await session.commit()
        return 0
    finally:
        await bot.session.close()
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m app.bot", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command")
    wh = sub.add_parser("webhook", help="manage the Telegram webhook")
    wh.add_argument("action", choices=["set", "delete", "info"])
    wh.add_argument(
        "--drop-pending", action="store_true", help="with delete: discard queued updates"
    )
    args = parser.parse_args(argv)
    if args.command == "webhook":
        return asyncio.run(run_webhook_command(args.action, args.drop_pending))
    return asyncio.run(run_polling())


if __name__ == "__main__":
    sys.exit(main())
