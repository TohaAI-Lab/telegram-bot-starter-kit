"""Private-chat access control and safe error handling for Aiogram 3."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, TelegramObject

from config import Settings


logger = logging.getLogger(__name__)
Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessMiddleware(BaseMiddleware):
    """Allow only private messages from users permitted by the configuration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        if not isinstance(event, Message):
            return None
        if event.chat.type != ChatType.PRIVATE or event.from_user is None:
            return None
        if not self.settings.is_allowed(event.from_user.id):
            await event.answer("Access denied.", parse_mode=None)
            return None
        return await handler(event, data)


class ErrorHandlingMiddleware(BaseMiddleware):
    """Report handler failures without exposing exception text or secrets."""

    async def __call__(
        self, handler: Handler, event: TelegramObject, data: dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as exc:
            # Exception messages and tracebacks can contain credentials or user data.
            logger.error("Handler failed (%s)", type(exc).__name__)
            if (
                isinstance(event, Message)
                and event.chat.type == ChatType.PRIVATE
            ):
                try:
                    await event.answer(
                        "Something went wrong. Please try again later.",
                        parse_mode=None,
                    )
                except Exception as reply_exc:
                    logger.warning(
                        "Could not send error reply (%s)", type(reply_exc).__name__
                    )
            return None
