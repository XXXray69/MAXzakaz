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
    "IFL": 0.03,
    "MINI_KASKO": 0.03,
    "KLESH": 0.02,
    "NS": 0.02,
    "OTHER": 0.02,
}

REFERRAL_BONUS_RATES: Dict[str, float] = {
    "OSAGO": 0.01,
    "KASKO": 0.05,
    "MORTGAGE": 0.03,
    "PROPERTY": 0.04,
    "LIFE": 0.03,
    "TRAVEL": 0.02,
    "IFL": 0.03,
    "MINI_KASKO": 0.03,
    "KLESH": 0.02,
    "NS": 0.02,
    "OTHER": 0.02,
}

VOLUNTARY_POLICY_TYPES = {
    "KASKO",
    "MORTGAGE",
    "PROPERTY",
    "LIFE",
    "TRAVEL",
    "IFL",
    "MINI_KASKO",
    "KLESH",
    "NS",
    "OTHER",
}

LOYALTY_TIERS = {
    "BRONZE": {"min_spent": 0.0},
    "SILVER": {"min_spent": 50000.0},
    "GOLD": {"min_spent": 150000.0},
    "VIP": {"min_spent": 400000.0},
}

PRODUCT_TEXTS = {
    "ОСАГО": (
        "ОСАГО — обязательное страхование автогражданской ответственности.\n\n"
        "Полис покрывает ответственность перед третьими лицами при ДТП.\n"
        "Подходит для обязательного оформления автомобиля."
    ),
    "КАСКО": (
        "КАСКО — добровольное страхование автомобиля.\n\n"
        "Покрывает риски угона, ущерба, повреждений, стихийных бедствий и других случаев "
        "в зависимости от условий программы."
    ),
    "Ипотека": (
        "Ипотека — страхование для ипотечных клиентов.\n\n"
        "Возможны варианты:\n"
        "— страхование жизни\n"
        "— страхование имущества\n"
        "— комплексная ипотечная защита\n\n"
        "Подберём оптимальный вариант под требования банка."
    ),
    "ИФЛ": (
        "ИФЛ — индивидуальное страхование физических лиц.\n\n"
        "Подберём программу защиты под личные цели клиента: имущество, риски, здоровье "
        "или иные страховые продукты."
    ),
    "Мини Каско": (
        "Мини Каско — облегчённый вариант КАСКО.\n\n"
        "Подходит тем, кто хочет базовую защиту автомобиля по более доступной стоимости."
    ),
    "Клещ": (
        "Страхование от укуса клеща.\n\n"
        "Помогает покрыть расходы на анализы, лечение и медицинскую помощь при страховом случае."
    ),
    "НС": (
        "НС — страхование от несчастных случаев.\n\n"
        "Обеспечивает финансовую защиту при травмах, временной потере трудоспособности "
        "и других последствиях несчастного случая."
    ),
    "Прочее": (
        "Прочее — другие страховые продукты и индивидуальные запросы.\n\n"
        "Если вы не нашли нужный вариант в списке, выберите этот пункт.\n"
        "Менеджер уточнит ваш запрос и подберёт подходящее решение."
    ),
}













