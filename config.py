"""Environment-based configuration for the Telegram Bot Starter Kit."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional


BASE_DIR = Path(__file__).resolve().parent


class ConfigError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    database_path: Path
    log_level: str
    allowed_user_ids: frozenset[int]

    def is_allowed(self, user_id: int) -> bool:
        """An empty allowlist permits all users."""
        return not self.allowed_user_ids or user_id in self.allowed_user_ids


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Read and validate settings without modifying the environment."""
    source = os.environ if env is None else env

    token = source.get("BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ConfigError("BOT_TOKEN is missing or has an invalid format.")

    log_level = source.get("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("LOG_LEVEL is invalid.")

    raw_path = source.get("DATABASE_PATH", "data/bot.sqlite3").strip()
    if not raw_path:
        raise ConfigError("DATABASE_PATH must not be empty.")
    database_path = Path(raw_path).expanduser()
    if not database_path.is_absolute():
        database_path = BASE_DIR / database_path

    raw_ids = source.get("ALLOWED_USER_IDS", "").strip()
    ids: set[int] = set()
    if raw_ids:
        for item in raw_ids.split(","):
            value = item.strip()
            if not re.fullmatch(r"[0-9]+", value):
                raise ConfigError("ALLOWED_USER_IDS must contain positive integers.")
            try:
                user_id = int(value)
            except ValueError:
                raise ConfigError("ALLOWED_USER_IDS contains an invalid integer.") from None
            if user_id <= 0:
                raise ConfigError("ALLOWED_USER_IDS must contain positive integers.")
            ids.add(user_id)

    return Settings(token, database_path, log_level, frozenset(ids))
