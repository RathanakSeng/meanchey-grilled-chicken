"""A fake aiogram HTTP session: records Bot API calls instead of hitting api.telegram.org."""

import time
from collections.abc import Callable
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, User, WebhookInfo

BOT_USER = User(id=1, is_bot=True, first_name="Mean Chey", username="meanchey_test_bot")


class RecordingSession(BaseSession):
    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        unreachable: bool = False,
    ) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.responses = responses or {}
        self.unreachable = unreachable

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (signature defined by aiogram)
    ) -> Any:
        self.requests.append(method)
        if self.unreachable:
            raise TelegramNetworkError(method=method, message="Request timeout error")
        name = type(method).__name__
        response = self.responses.get(name)
        if isinstance(response, Callable):
            return response(method)
        if response is not None:
            return response
        return _default_response(name, method)

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass

    def calls(self, name: str) -> list[Any]:
        return [m for m in self.requests if type(m).__name__ == name]


def _default_response(name: str, method: Any) -> Any:
    if name == "GetMe":
        return BOT_USER
    if name == "GetWebhookInfo":
        return WebhookInfo(url="", has_custom_certificate=False, pending_update_count=0)
    if name == "SendMessage":
        return Message(
            message_id=100,
            date=int(time.time()),
            chat=Chat(id=method.chat_id, type="private"),
            text=method.text,
        )
    return True  # setWebhook, deleteWebhook, setMyCommands, …


def command_update(
    text: str, tg_id: int = 4242, username: str | None = "some_user", update_id: int = 1
) -> dict[str, Any]:
    """A raw Telegram update (as JSON) for a private-chat command message."""
    sender: dict[str, Any] = {"id": tg_id, "is_bot": False, "first_name": "Dara"}
    if username:
        sender["username"] = username
    command = text.split()[0]
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(time.time()),
            "chat": {"id": tg_id, "type": "private", "first_name": "Dara"},
            "from": sender,
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}],
        },
    }
