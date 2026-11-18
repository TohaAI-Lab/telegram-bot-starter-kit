"""Asynchronous access to the starter kit's local SQLite database."""

import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class Database:
    """File-backed SQLite storage; each operation owns its connection."""

    def __init__(self, path: Path | str) -> None:
        if str(path) == ":memory:":
            raise ValueError("A file-backed database is required.")
        self.path = Path(path).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), timeout=10.0)

    async def initialize(self) -> None:
        """Create the data directory and schema before polling starts."""
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY CHECK (user_id > 0),
                    start_count INTEGER NOT NULL CHECK (start_count > 0),
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _validate_user_id(user_id: int) -> None:
        if type(user_id) is not int or not 0 < user_id <= 2**63 - 1:
            raise ValueError("user_id must be a positive SQLite integer.")

    async def record_start(self, user_id: int) -> int:
        """Atomically record a /start command and return the updated count."""
        self._validate_user_id(user_id)
        return await asyncio.to_thread(self._record_start, user_id)

    def _record_start(self, user_id: int) -> int:
        timestamp = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO users (user_id, start_count, first_seen_utc, last_seen_utc)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    start_count = users.start_count + 1,
                    last_seen_utc = MAX(users.last_seen_utc, excluded.last_seen_utc)
                """,
                (user_id, timestamp, timestamp),
            )
            row = connection.execute(
                "SELECT start_count FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row[0])

    async def get_start_count(self, user_id: int) -> int:
        """Return the user's /start count, or zero for an unknown user."""
        self._validate_user_id(user_id)
        return await asyncio.to_thread(self._get_start_count, user_id)

    def _get_start_count(self, user_id: int) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT start_count FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row[0]) if row is not None else 0

    async def count_users(self) -> int:
        """Return the number of distinct users who have used /start."""
        return await asyncio.to_thread(self._count_users)

    def _count_users(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
