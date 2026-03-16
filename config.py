from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


APP_BASE_URL = _env("APP_BASE_URL", "")
DATABASE_URL = _env("DATABASE_URL", "sqlite:///./loyalty_system.db")
ADMIN_TOKEN = _env("ADMIN_TOKEN", "change-me")

MAX_API_BASE = _env("MAX_API_BASE", "https://platform-api.max.ru")
MAX_BOT_TOKEN = _env("MAX_BOT_TOKEN", "")
MAX_BOT_USERNAME = _env("MAX_BOT_USERNAME", "your_bot")

WEBHOOK_SECRET = _env("WEBHOOK_SECRET", "")
OWNER_USER_ID = _env("OWNER_USER_ID", "")













