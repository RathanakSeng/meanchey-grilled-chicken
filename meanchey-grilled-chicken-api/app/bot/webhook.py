"""Telegram webhook endpoint: POST /api/telegram/webhook (not part of the versioned API)."""

import hmac
import logging

from aiogram.types import Update
from fastapi import APIRouter, Request, Response
from starlette.exceptions import HTTPException

from app.bot.runtime import TelegramRuntime

log = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

router = APIRouter(prefix="/api/telegram", include_in_schema=False)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> Response:
    runtime: TelegramRuntime | None = getattr(request.app.state, "telegram", None)
    if runtime is None:
        # Polling / off mode, or no bot token: behave as if the endpoint doesn't exist.
        raise HTTPException(status_code=404)

    received = request.headers.get(SECRET_HEADER, "")
    if not hmac.compare_digest(received.encode(), runtime.secret.encode()):
        log.warning(
            "rejected Telegram webhook call: %s secret token (client %s)",
            "missing" if not received else "invalid",
            request.client.host if request.client else "unknown",
        )
        return Response(status_code=401)

    # From here on always answer 200: a non-2xx makes Telegram redeliver the same update.
    try:
        update = Update.model_validate(await request.json(), context={"bot": runtime.bot})
        await runtime.dp.feed_update(runtime.bot, update)
    except Exception:
        log.exception("error while handling Telegram update")
    return Response(status_code=200)
