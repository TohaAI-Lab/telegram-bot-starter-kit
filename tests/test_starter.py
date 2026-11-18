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
