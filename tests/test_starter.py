"""Offline regression tests for TohaAI Lab's Telegram Bot Starter Kit."""

import asyncio
import importlib.util
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config import BASE_DIR, ConfigError, load_settings
from database.storage import Database
from services.bot_service import BotService

# Synthetic credential, never issued by Telegram or used over the network.
TOKEN = "123456789:offline_test_token_not_real"


class ConfigurationTests(unittest.TestCase):
    def test_defaults(self):
        settings = load_settings({"BOT_TOKEN": TOKEN})
        self.assertEqual(settings.database_path, BASE_DIR / "data/bot.sqlite3")
        self.assertEqual(settings.log_level, "INFO")
        self.assertTrue(settings.is_allowed(123))
        self.assertNotIn(TOKEN, repr(settings))

    def test_custom_settings(self):
        settings = load_settings({"BOT_TOKEN": TOKEN, "LOG_LEVEL": "debug",
                                  "DATABASE_PATH": "custom/db.sqlite3",
                                  "ALLOWED_USER_IDS": "12, 34,12"})
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.database_path, BASE_DIR / "custom/db.sqlite3")
        self.assertEqual(settings.allowed_user_ids, frozenset({12, 34}))
        self.assertTrue(settings.is_allowed(12))
        self.assertFalse(settings.is_allowed(99))

    def test_invalid_settings(self):
        for key, value in [("BOT_TOKEN", ""), ("BOT_TOKEN", "invalid"),
                           ("LOG_LEVEL", "verbose"), ("DATABASE_PATH", " "),
                           ("ALLOWED_USER_IDS", "0"), ("ALLOWED_USER_IDS", "1,"),
                           ("ALLOWED_USER_IDS", "abc")]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ConfigError):
                    load_settings({"BOT_TOKEN": TOKEN, key: value})


class StorageAndServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "data" / "test.sqlite3"
        self.database = Database(self.path)
        await self.database.initialize()
        self.service = BotService(self.database)

    async def test_initialization_is_idempotent(self):
        await self.database.record_start(1)
        await self.database.initialize()
        self.assertEqual(await self.database.get_start_count(1), 1)

    async def test_persistence_and_isolation(self):
        self.assertEqual(await self.database.record_start(1), 1)
        self.assertEqual(await self.database.record_start(1), 2)
        await self.database.record_start(2)
        reopened = Database(self.path)
        self.assertEqual(await reopened.get_start_count(1), 2)
        self.assertEqual(await reopened.get_start_count(2), 1)
        self.assertEqual(await reopened.get_start_count(3), 0)
        self.assertEqual(await reopened.count_users(), 2)

    async def test_concurrent_starts_are_atomic(self):
        results = await asyncio.gather(*(self.database.record_start(7) for _ in range(20)))
        self.assertEqual(sorted(results), list(range(1, 21)))
        self.assertEqual(await self.database.get_start_count(7), 20)

    async def test_invalid_user_ids(self):
        for value in (0, -1, True, "123", 2**63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.database.record_start(value)
                with self.assertRaises(ValueError):
                    await self.database.get_start_count(value)
        with self.assertRaises(ValueError):
            Database(":memory:")

    async def test_timestamps_are_utc(self):
        await self.database.record_start(5)
        await self.database.record_start(5)
        with closing(sqlite3.connect(self.path)) as connection:
            first, last = connection.execute(
                "SELECT first_seen_utc, last_seen_utc FROM users WHERE user_id = 5"
            ).fetchone()
        first, last = datetime.fromisoformat(first), datetime.fromisoformat(last)
        self.assertEqual(first.utcoffset(), timezone.utc.utcoffset(None))
        self.assertEqual(last.utcoffset(), timezone.utc.utcoffset(None))
        self.assertLessEqual(first, last)

    async def test_service_replies(self):
        self.assertIn("count: 0", await self.service.status(1))
        self.assertIn("Welcome!", await self.service.start(1))
        self.assertIn("Welcome back!", await self.service.start(1))
        self.assertIn("count: 2", await self.service.status(1))
        self.assertIn("count: 0", await self.service.status(2))
        for command in ("/start", "/help", "/status"):
            self.assertIn(command, self.service.help())


# Keep core tests runnable without dependencies. CI must install requirements.txt
# and explicitly verify both dependencies are importable before running this suite.
HAS_DEPS = all(importlib.util.find_spec(name) is not None for name in ("aiogram", "dotenv"))
if HAS_DEPS:
    from aiogram import Bot
    from aiogram.types import Message, Update
    from bot import TokenRedactingFormatter, create_dispatcher, run


@unittest.skipUnless(HAS_DEPS, "Install requirements.txt for Aiogram integration tests")
class TelegramIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.settings = load_settings({"BOT_TOKEN": TOKEN,
                                      "DATABASE_PATH": str(Path(directory.name) / "bot.sqlite3"),
                                      "ALLOWED_USER_IDS": "10,20"})
        self.database = Database(self.settings.database_path)
        await self.database.initialize()
        self.dispatcher = create_dispatcher(self.settings, BotService(self.database))
        self.bot = Bot(token=TOKEN)
        self.addAsyncCleanup(self.bot.session.close)
        # A real Bot and Dispatcher, but all Telegram I/O is intercepted.
        self.request = AsyncMock(side_effect=AssertionError("Unexpected Telegram API request"))
        guard = patch.object(self.bot.session, "make_request", self.request)
        guard.start()
        self.addCleanup(guard.stop)
        self.update_id = 0

    async def dispatch(self, text, user_id=10, chat_type="private"):
        self.update_id += 1
        update = Update.model_validate({"update_id": self.update_id, "message": {
            "message_id": self.update_id, "date": 1700000000, "text": text,
            "chat": {"id": user_id if chat_type == "private" else -1001, "type": chat_type},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        }})
        with patch.object(Message, "answer", new_callable=AsyncMock) as answer:
            await self.dispatcher.feed_update(self.bot, update)
            self.request.assert_not_called()
            return answer

    async def test_real_dispatcher_commands(self):
        answer = await self.dispatch("/start")
        answer.assert_awaited_once()
        self.assertIn("Welcome!", answer.await_args.args[0])
        answer = await self.dispatch("/help")
        answer.assert_awaited_once()
        self.assertIn("/status", answer.await_args.args[0])
        answer = await self.dispatch("/status")
        self.assertIn("count: 1", answer.await_args.args[0])
        answer = await self.dispatch("/status", user_id=20)
        self.assertIn("count: 0", answer.await_args.args[0])

    async def test_access_control(self):
        answer = await self.dispatch("/start", user_id=99)
        answer.assert_awaited_once_with("Access denied.", parse_mode=None)
        self.assertEqual(await self.database.count_users(), 0)
        answer = await self.dispatch("/start", chat_type="group")
        answer.assert_not_awaited()
        self.assertEqual(await self.database.count_users(), 0)

    async def test_handler_error_is_sanitized(self):
        with patch.object(self.database, "record_start", new_callable=AsyncMock,
                          side_effect=RuntimeError(TOKEN)):
            with self.assertLogs("middlewares.security", level="ERROR") as logs:
                answer = await self.dispatch("/start")
        answer.assert_awaited_once_with("Something went wrong. Please try again later.", parse_mode=None)
        self.assertNotIn(TOKEN, "\n".join(logs.output))

    async def test_webhook_is_not_deleted(self):
        fake = AsyncMock()
        fake.get_webhook_info.return_value = SimpleNamespace(url="https://example.invalid/hook")
        dispatcher = SimpleNamespace(start_polling=AsyncMock())
        with patch("bot.Bot", return_value=fake), patch("bot.create_dispatcher", return_value=dispatcher):
            with self.assertLogs("bot", level="ERROR"):
                with self.assertRaises(ConfigError):
                    await run(self.settings)
        fake.delete_webhook.assert_not_called()
        dispatcher.start_polling.assert_not_called()
        fake.session.close.assert_awaited_once()

    async def test_polling_configuration_and_cleanup(self):
        fake = AsyncMock()
        fake.get_webhook_info.return_value = SimpleNamespace(url="")
        dispatcher = SimpleNamespace(start_polling=AsyncMock(),
                                     resolve_used_update_types=lambda: ["message"])
        with patch("bot.Bot", return_value=fake), patch("bot.create_dispatcher", return_value=dispatcher):
            await run(self.settings)
        dispatcher.start_polling.assert_awaited_once_with(
            fake, allowed_updates=["message"], close_bot_session=False,
            tasks_concurrency_limit=16, tasks_shutdown_timeout=20, handle_as_tasks=True,
        )
        fake.session.close.assert_awaited_once()
        fake.delete_webhook.assert_not_called()

    async def test_logging_redacts_token(self):
        from urllib.parse import quote
        formatter = TokenRedactingFormatter(TOKEN)
        record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                                   "%s %s", (TOKEN, quote(TOKEN, safe="")), None)
        rendered = formatter.format(record)
        self.assertNotIn(TOKEN, rendered)
        self.assertNotIn(quote(TOKEN, safe=""), rendered)
        self.assertEqual(rendered.count("[REDACTED]"), 2)


if __name__ == "__main__":
    unittest.main()
