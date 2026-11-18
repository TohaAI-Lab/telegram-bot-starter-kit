"""Telegram-independent command logic for the starter kit."""

from database.storage import Database


class BotService:
    """Build plain-text replies; transport and access checks live elsewhere."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def start(self, user_id: int) -> str:
        """Record a /start command and return a welcome message."""
        count = await self.database.record_start(user_id)
        greeting = "Welcome!" if count == 1 else "Welcome back!"
        return (
            f"{greeting}\n"
            "This bot is powered by the TohaAI Lab Telegram Bot Starter Kit.\n"
            f"Your /start count: {count}\n\n"
            "Use /help to see available commands."
        )

    @staticmethod
    def help() -> str:
        """List supported commands without accessing the database."""
        return (
            "Available commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/status - Check the bot and your personal /start count"
        )

    async def status(self, user_id: int) -> str:
        """Report responsiveness and the requesting user's own count."""
        count = await self.database.get_start_count(user_id)
        return (
            "Bot status: online\n"
            "Database: available\n"
            f"Your /start count: {count}"
        )
