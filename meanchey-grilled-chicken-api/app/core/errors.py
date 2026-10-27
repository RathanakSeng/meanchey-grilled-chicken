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
    # Step 3: satay sachets used differ from the pack counts and there's no comment.
    PRODUCTION_SACHET_COMMENT_REQUIRED = "PRODUCTION_SACHET_COMMENT_REQUIRED"
    # A reopen / cancel would take back stock that already left in orders.
    PRODUCTION_STOCK_ALREADY_USED = "PRODUCTION_STOCK_ALREADY_USED"
    # Orders
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    ORDER_CONFLICT = "ORDER_CONFLICT"
    ORDER_INVALID_STATUS = "ORDER_INVALID_STATUS"
    ORDER_CONTAINERS_REQUIRED = "ORDER_CONTAINERS_REQUIRED"
    ORDER_CONTAINER_STATE = "ORDER_CONTAINER_STATE"
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
    # Clear stock: impacts found and `acknowledge_impacts` not sent.
    INVENTORY_CLEAR_UNACKNOWLEDGED = "INVENTORY_CLEAR_UNACKNOWLEDGED"
    INVENTORY_CLEAR_NOT_FOUND = "INVENTORY_CLEAR_NOT_FOUND"
    # Materials (inventory items added by hand)
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    MATERIAL_UNIT_LOCKED = "MATERIAL_UNIT_LOCKED"
    MATERIAL_ARCHIVED = "MATERIAL_ARCHIVED"
    MATERIAL_SYSTEM_LOCKED = "MATERIAL_SYSTEM_LOCKED"
    DUPLICATE_MATERIAL_NAME = "DUPLICATE_MATERIAL_NAME"
    # Preparations (satay sachets, packaging materials)
    PREPARATION_NOT_FOUND = "PREPARATION_NOT_FOUND"
    PREPARATION_CONFLICT = "PREPARATION_CONFLICT"
    PREPARATION_CANCELLED = "PREPARATION_CANCELLED"
    # The action isn't allowed in the preparation's status (e.g. saving a finished one).
    PREPARATION_INVALID_STATUS = "PREPARATION_INVALID_STATUS"
    # Attendance (check-in / check-out from the Mini App, corrections)
    ATTENDANCE_NOT_REQUIRED = "ATTENDANCE_NOT_REQUIRED"
    ATTENDANCE_WORKPLACE_NOT_SET = "ATTENDANCE_WORKPLACE_NOT_SET"
    ATTENDANCE_TOO_EARLY = "ATTENDANCE_TOO_EARLY"
    ATTENDANCE_NO_SHIFT_NOW = "ATTENDANCE_NO_SHIFT_NOW"
    ATTENDANCE_CHECKIN_CLOSED = "ATTENDANCE_CHECKIN_CLOSED"
    ATTENDANCE_CHECKOUT_TOO_EARLY = "ATTENDANCE_CHECKOUT_TOO_EARLY"
    ATTENDANCE_CHECKOUT_CLOSED = "ATTENDANCE_CHECKOUT_CLOSED"
    ATTENDANCE_ALREADY_CHECKED_IN = "ATTENDANCE_ALREADY_CHECKED_IN"
    ATTENDANCE_NOT_CHECKED_IN = "ATTENDANCE_NOT_CHECKED_IN"
    ATTENDANCE_ALREADY_CHECKED_OUT = "ATTENDANCE_ALREADY_CHECKED_OUT"
    ATTENDANCE_TOO_FAR = "ATTENDANCE_TOO_FAR"
    ATTENDANCE_RECORD_NOT_FOUND = "ATTENDANCE_RECORD_NOT_FOUND"
    ATTENDANCE_RECORD_EXISTS = "ATTENDANCE_RECORD_EXISTS"
    ATTENDANCE_WORKPLACE_NOT_FOUND = "ATTENDANCE_WORKPLACE_NOT_FOUND"
    WORKPLACE_IN_USE = "WORKPLACE_IN_USE"
    WORKPLACE_IS_DEFAULT = "WORKPLACE_IS_DEFAULT"
    WORKPLACE_NAME_TAKEN = "WORKPLACE_NAME_TAKEN"
    WORKPLACE_ARCHIVED = "WORKPLACE_ARCHIVED"
    ATTENDANCE_DAY_OFF = "ATTENDANCE_DAY_OFF"
    ATTENDANCE_HOLIDAY_NOT_FOUND = "ATTENDANCE_HOLIDAY_NOT_FOUND"
    ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND = "ATTENDANCE_SCHEDULE_VERSION_NOT_FOUND"
    ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT = "ATTENDANCE_SCHEDULE_VERSION_IN_EFFECT"
    ATTENDANCE_SCHEDULE_INVALID = "ATTENDANCE_SCHEDULE_INVALID"
    ATTENDANCE_SCHEDULE_CONFLICT = "ATTENDANCE_SCHEDULE_CONFLICT"
    ATTENDANCE_EXCEPTION_NOT_FOUND = "ATTENDANCE_EXCEPTION_NOT_FOUND"
    # Before the employee's attendance start date (details.start_date).
    ATTENDANCE_NOT_STARTED = "ATTENDANCE_NOT_STARTED"
    # The start date has arrived: it can no longer be edited.
    ATTENDANCE_START_LOCKED = "ATTENDANCE_START_LOCKED"
    # Monthly requests: the window isn't open / is closed (details.opens, details.closes), one per
    # month (also after a rejection), the split must equal the missing time (details.expected,
    # details.given), already reviewed, and a month locked by a pending / approved request.
    ATTENDANCE_REQUEST_WINDOW_CLOSED = "ATTENDANCE_REQUEST_WINDOW_CLOSED"
    ATTENDANCE_REQUEST_EXISTS = "ATTENDANCE_REQUEST_EXISTS"
    ATTENDANCE_REQUEST_SPLIT_MISMATCH = "ATTENDANCE_REQUEST_SPLIT_MISMATCH"
    ATTENDANCE_REQUEST_NOT_FOUND = "ATTENDANCE_REQUEST_NOT_FOUND"
    ATTENDANCE_REQUEST_NOT_PENDING = "ATTENDANCE_REQUEST_NOT_PENDING"
    ATTENDANCE_REQUEST_NOT_NEEDED = "ATTENDANCE_REQUEST_NOT_NEEDED"
    ATTENDANCE_MONTH_LOCKED = "ATTENDANCE_MONTH_LOCKED"
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
