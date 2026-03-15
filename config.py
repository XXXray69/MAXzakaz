from __future__ import annotations

import os

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://example.com")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./loyalty_system.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")

MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api.max.ru")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "your_bot")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
OWNER_USER_ID = os.getenv("OWNER_USER_ID", "")













