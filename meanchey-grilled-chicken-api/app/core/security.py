import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings
from app.core.errors import AppError, ErrorCode

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_ttl_minutes),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret,
            algorithms=[s.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AppError(401, ErrorCode.TOKEN_EXPIRED, "Access token expired") from e
    except jwt.InvalidTokenError as e:
        raise AppError(401, ErrorCode.INVALID_TOKEN, "Invalid access token") from e
    if payload.get("type") != "access":
        raise AppError(401, ErrorCode.INVALID_TOKEN, "Invalid access token")
    try:
        return uuid.UUID(payload["sub"])
    except ValueError as e:
        raise AppError(401, ErrorCode.INVALID_TOKEN, "Invalid access token") from e


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, token_hash)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_token(raw: str) -> str:
    """SHA-256 hex digest of a high-entropy random token (refresh tokens, Telegram link tokens)."""
    return hashlib.sha256(raw.encode()).hexdigest()


hash_refresh_token = hash_token
