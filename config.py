from __future__ import annotations

import os
from typing import Dict

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://example.com")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./loyalty_system.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")

MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api.max.ru")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "your_bot")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "secret")
OWNER_USER_ID = os.getenv("OWNER_USER_ID", "")

CASHBACK_THRESHOLD = float(os.getenv("CASHBACK_THRESHOLD", "1000"))
LOYALTY_PERIOD_DAYS = int(os.getenv("LOYALTY_PERIOD_DAYS", "365"))

POLICY_BONUS_RATES: Dict[str, float] = {
    "OSAGO": 0.01,
    "KASKO": 0.05,
    "MORTGAGE": 0.03,
    "PROPERTY": 0.04,
    "LIFE": 0.03,
    "TRAVEL": 0.02,
}

REFERRAL_BONUS_RATES: Dict[str, float] = {
    "OSAGO": 0.01,
    "KASKO": 0.05,
    "MORTGAGE": 0.03,
    "PROPERTY": 0.04,
    "LIFE": 0.03,
    "TRAVEL": 0.02,
}

VOLUNTARY_POLICY_TYPES = {"KASKO", "MORTGAGE", "PROPERTY", "LIFE", "TRAVEL"}

LOYALTY_TIERS = {
    "BRONZE": {"min_spent": 0.0},
    "SILVER": {"min_spent": 50000.0},
    "GOLD": {"min_spent": 150000.0},
    "VIP": {"min_spent": 400000.0},
}

MESSAGE_HELP = (
    "Доступные кнопки:\n"
    "Баланс — посмотреть бонусный баланс\n"
    "Уровень — посмотреть уровень лояльности\n"
    "Реферал — получить реферальную ссылку\n"
    "Вывод 1000 — оставить заявку на вывод\n"
    "Тарифы — выбрать интересующий вид страхования\n"
    "Связаться — передать запрос менеджеру"
)

PRODUCT_TEXTS = {
    "OSAGO": "ОСАГО — обязательное страхование автогражданской ответственности.",
    "KASKO": "КАСКО — защита автомобиля от ущерба, угона и других рисков.",
    "MORTGAGE": "Ипотечное страхование — защита объекта, жизни и титула по требованиям банка.",
    "PROPERTY": "Страхование имущества — защита квартиры, дома, ремонта и вещей.",
    "LIFE": "Страхование жизни — финансовая защита семьи и близких.",
    "TRAVEL": "Страхование путешествий — защита на время поездки по России и за рубежом.",
}






