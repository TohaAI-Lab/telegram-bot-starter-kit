
"""Private-chat command handlers for the Telegram Bot Starter Kit."""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from services.bot_service import BotService


async def start_handler(message: Message, bot_service: BotService) -> None:
    """Register the sender's /start command and send their welcome reply."""
    if message.from_user is None:
        return
    reply = await bot_service.start(message.from_user.id)
    await message.answer(reply, parse_mode=None)


async def help_handler(message: Message, bot_service: BotService) -> None:
    """Show the list of available commands."""
    if message.from_user is None:
        return
    await message.answer(bot_service.help(), parse_mode=None)


async def status_handler(message: Message, bot_service: BotService) -> None:
    """Send only the requesting user's own statistics."""
    if message.from_user is None:
        return
    reply = await bot_service.status(message.from_user.id)
    await message.answer(reply, parse_mode=None)


def create_router() -> Router:
    """Create a fresh router; the dispatcher supplies bot_service by name."""
    router = Router(name="commands")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.message.register(start_handler, CommandStart())
    router.message.register(help_handler, Command("help"))
    router.message.register(status_handler, Command("status"))
    return router





