import re

from app.core.errors import AppError, ErrorCode

SUPERADMIN_USERNAME = "superadmin"

_TELEGRAM_USERNAME_RE = re.compile(r"[a-z0-9_]{5,32}")
# Login names that can never be used as a Telegram username.
_RESERVED = frozenset({SUPERADMIN_USERNAME})


def normalize_login(raw: str) -> str:
    """Normalize a login identifier without validating it."""
    return raw.strip().removeprefix("@").lower()


def normalize_telegram_username(raw: str) -> str:
    """Strip a leading '@', lowercase, and validate (5-32 chars of [a-z0-9_])."""
    value = normalize_login(raw)
    if not _TELEGRAM_USERNAME_RE.fullmatch(value) or value in _RESERVED:
        raise AppError(
            422,
            ErrorCode.INVALID_TELEGRAM_USERNAME,
            "Telegram username must be 5-32 characters of a-z, 0-9 or _",
        )
    return value
