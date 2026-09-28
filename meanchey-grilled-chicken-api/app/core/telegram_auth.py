"""Validation of Telegram Mini App initData.

See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.core.errors import AppError, ErrorCode


@dataclass(frozen=True)
class TelegramUser:
    id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None


def _invalid(reason: str) -> AppError:
    return AppError(401, ErrorCode.INVALID_TELEGRAM_DATA, f"Invalid Telegram data: {reason}")


def compute_init_data_hash(fields: dict[str, str], bot_token: str) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(
    init_data: str, bot_token: str, max_age_seconds: int, now: int | None = None
) -> TelegramUser:
    if not bot_token:
        raise AppError(503, ErrorCode.TELEGRAM_NOT_CONFIGURED, "Telegram bot is not configured")
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as e:
        raise _invalid("malformed") from e

    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise _invalid("missing hash")
    if not hmac.compare_digest(compute_init_data_hash(fields, bot_token), received_hash):
        raise _invalid("hash mismatch")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError) as e:
        raise _invalid("missing auth_date") from e
    current = int(time.time()) if now is None else now
    if current - auth_date > max_age_seconds:
        raise AppError(401, ErrorCode.TELEGRAM_DATA_EXPIRED, "Telegram data has expired")

    try:
        user = json.loads(fields["user"])
        return TelegramUser(
            id=int(user["id"]),
            username=user.get("username"),
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            language_code=user.get("language_code"),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise _invalid("missing user") from e
