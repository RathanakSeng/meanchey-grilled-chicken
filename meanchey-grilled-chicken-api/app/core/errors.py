from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    """Stable, machine-readable error codes. The UI translates these; never rename one."""

    # Authentication
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    WRONG_CURRENT_PASSWORD = "WRONG_CURRENT_PASSWORD"
    PASSWORD_TOO_SHORT = "PASSWORD_TOO_SHORT"
    PASSWORD_EQUALS_USERNAME = "PASSWORD_EQUALS_USERNAME"
    # Telegram
    TELEGRAM_NOT_CONFIGURED = "TELEGRAM_NOT_CONFIGURED"
    INVALID_TELEGRAM_DATA = "INVALID_TELEGRAM_DATA"
    TELEGRAM_DATA_EXPIRED = "TELEGRAM_DATA_EXPIRED"
    USER_NOT_REGISTERED = "USER_NOT_REGISTERED"
    # The requester has no Telegram account bound (open the Mini App from the bot once).
    TELEGRAM_NOT_LINKED = "TELEGRAM_NOT_LINKED"
    # Telegram refused the message or couldn't be reached.
    TELEGRAM_SEND_FAILED = "TELEGRAM_SEND_FAILED"
    # Authorization
    FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    MISSING_PERMISSION = "MISSING_PERMISSION"
    PERMISSION_NOT_HELD = "PERMISSION_NOT_HELD"
    PERMISSION_NOT_ASSIGNABLE = "PERMISSION_NOT_ASSIGNABLE"
    PERMISSION_NOT_FOUND = "PERMISSION_NOT_FOUND"
    PERMISSION_GRANT_RESTRICTED = "PERMISSION_GRANT_RESTRICTED"
    FEATURE_NOT_FOUND = "FEATURE_NOT_FOUND"
    FEATURE_NOT_APPLICABLE = "FEATURE_NOT_APPLICABLE"
    # Users
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_INACTIVE = "USER_INACTIVE"
    INVALID_TELEGRAM_USERNAME = "INVALID_TELEGRAM_USERNAME"
    DUPLICATE_TELEGRAM_USERNAME = "DUPLICATE_TELEGRAM_USERNAME"
    # No longer raised (several GMs are allowed, up to the role limit); codes are never removed.
    GM_ALREADY_EXISTS = "GM_ALREADY_EXISTS"
    ROLE_LIMIT_REACHED = "ROLE_LIMIT_REACHED"
    POSITION_REQUIRED = "POSITION_REQUIRED"
    POSITION_NOT_ALLOWED = "POSITION_NOT_ALLOWED"
    # Partners (suppliers, customers)
    SUPPLIER_NOT_FOUND = "SUPPLIER_NOT_FOUND"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    DUPLICATE_PHONE = "DUPLICATE_PHONE"
    INVALID_PHONE = "INVALID_PHONE"
    SUPPLIER_INACTIVE = "SUPPLIER_INACTIVE"
    # Production
    PRODUCTION_NOT_FOUND = "PRODUCTION_NOT_FOUND"
    PRODUCTION_STEP_NOT_READY = "PRODUCTION_STEP_NOT_READY"
    PRODUCTION_STEP_FINISHED = "PRODUCTION_STEP_FINISHED"
    # No longer raised (editing a step reopens the later ones too); kept: codes are never removed.
    PRODUCTION_STEP_LOCKED = "PRODUCTION_STEP_LOCKED"
    PRODUCTION_BALANCE_MISMATCH = "PRODUCTION_BALANCE_MISMATCH"
    PRODUCTION_CONFLICT = "PRODUCTION_CONFLICT"
    PRODUCTION_CANCELLED = "PRODUCTION_CANCELLED"
    PRODUCTION_COMPLETED = "PRODUCTION_COMPLETED"
    # Packaging plan (between steps 2 and 3)
    PRODUCTION_PLAN_REQUIRED = "PRODUCTION_PLAN_REQUIRED"
    PRODUCTION_PLAN_LOCKED = "PRODUCTION_PLAN_LOCKED"
    PRODUCTION_PLAN_EXCEEDS_OUTPUT = "PRODUCTION_PLAN_EXCEEDS_OUTPUT"
    PRODUCTION_PLAN_COMMENT_REQUIRED = "PRODUCTION_PLAN_COMMENT_REQUIRED"
    # A reopen / cancel would take back stock that already left in orders.
    PRODUCTION_STOCK_ALREADY_USED = "PRODUCTION_STOCK_ALREADY_USED"
    # Orders
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_CONFLICT = "ORDER_CONFLICT"
    ORDER_INVALID_STATUS = "ORDER_INVALID_STATUS"
    CUSTOMER_INACTIVE = "CUSTOMER_INACTIVE"
    DRIVER_NOT_ALLOWED = "DRIVER_NOT_ALLOWED"
    # Documents (delivery note PDF): the renderer is missing or took too long.
    DOCUMENT_UNAVAILABLE = "DOCUMENT_UNAVAILABLE"
    # Notifications
    NOTIFICATION_NOT_FOUND = "NOTIFICATION_NOT_FOUND"
    # Inventory
    INVENTORY_INSUFFICIENT = "INVENTORY_INSUFFICIENT"
    INVENTORY_ITEM_NOT_FOUND = "INVENTORY_ITEM_NOT_FOUND"
    INVENTORY_ITEM_PRODUCTION_ONLY = "INVENTORY_ITEM_PRODUCTION_ONLY"
    # Generic
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    HTTP_ERROR = "HTTP_ERROR"


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


# Pydantic lists every allowed value for enums/literals ("Input should be 'superadmin', ...").
# That would reveal roles to people who can't see them, so those messages are replaced.
_ENUM_ERROR_TYPES = frozenset({"enum", "literal_error"})


def _safe_msg(error: dict[str, Any]) -> str:
    if error["type"] in _ENUM_ERROR_TYPES:
        return "Input is not one of the allowed values"
    return str(error["msg"])


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": [str(p) for p in e["loc"]], "type": e["type"], "msg": _safe_msg(e)}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(
                ErrorCode.VALIDATION_ERROR, "Request validation failed", {"fields": fields}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: ErrorCode.NOT_FOUND, 405: ErrorCode.METHOD_NOT_ALLOWED}.get(
            exc.status_code, ErrorCode.HTTP_ERROR
        )
        return JSONResponse(status_code=exc.status_code, content=_error_body(code, str(exc.detail)))
