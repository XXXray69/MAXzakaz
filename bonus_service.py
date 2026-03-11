from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from models import BonusLedger, BroadcastLog, Client, Policy, WithdrawalRequest


def _max_headers() -> dict:
    return {
        "Authorization": config.MAX_BOT_TOKEN,
        "Content-Type": "application/json",
    }


def send_max_notification(max_user_id: str, message: str, buttons: Optional[list] = None) -> None:
    if not config.MAX_BOT_TOKEN:
        print(f"[MAX disabled -> {max_user_id}] {message}")
        return

    body = {"text": message}

    if buttons:
        body["attachments"] = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": buttons
                },
            }
        ]

    response = None
    try:
        response = requests.post(
            f"{config.MAX_API_BASE}/messages",
            headers=_max_headers(),
            params={"user_id": max_user_id},
            json=body,
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[MAX send error] user_id={max_user_id} error={exc}")
        if response is not None:
            print(f"[MAX send error body] {response.text}")


def answer_callback(callback_id: str, text: str, notification: bool = False) -> None:
    if not config.MAX_BOT_TOKEN or not callback_id:
        return

    response = None
    try:
        response = requests.post(
            f"{config.MAX_API_BASE}/messages/callback",
            headers=_max_headers(),
            json={
                "callback_id": callback_id,
                "text": text,
                "notification": notification,
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[MAX callback answer error] callback_id={callback_id} error={exc}")
        if response is not None:
            print(f"[MAX callback answer body] {response.text}")


def notify_owner(text: str) -> None:
    if not config.OWNER_USER_ID:
        print(f"[OWNER notify skipped] {text}")
        return
    send_max_notification(config.OWNER_USER_ID, text)


def generate_referral_code() -> str:
    return f"REF{secrets.token_hex(4).upper()}"


def generate_referral_link(client: Client) -> str:
    return f"https://max.ru/{config.MAX_BOT_USERNAME}?start={client.referral_code}"


def get_main_menu_buttons() -> list:
    return [
        [
            {"type": "callback", "text": "Баланс", "payload": "BALANCE"},
            {"type": "callback", "text": "Уровень", "payload": "LEVEL"},
        ],
        [
            {"type": "callback", "text": "Реферал", "payload": "REFERRAL"},
            {"type": "callback", "text": "Вывод 1000", "payload": "WITHDRAW_1000"},
        ],
        [
            {"type": "callback", "text": "Тарифы", "payload": "PRODUCTS"},
            {"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER"},
        ],
        [
            {"type": "callback", "text": "Помощь", "payload": "HELP"},
        ],
    ]


def get_products_buttons() -> list:
    return [
        [
            {"type": "callback", "text": "ОСАГО", "payload": "PRODUCT_OSAGO"},
            {"type": "callback", "text": "КАСКО", "payload": "PRODUCT_KASKO"},
        ],
        [
            {"type": "callback", "text": "Ипотека", "payload": "PRODUCT_MORTGAGE"},
            {"type": "callback", "text": "Имущество", "payload": "PRODUCT_PROPERTY"},
        ],
        [
            {"type": "callback", "text": "Жизнь", "payload": "PRODUCT_LIFE"},
            {"type": "callback", "text": "Путешествия", "payload": "PRODUCT_TRAVEL"},
        ],
        [
            {"type": "callback", "text": "Назад", "payload": "BACK_MAIN"},
        ],
    ]


def get_back_to_main_buttons() -> list:
    return [[{"type": "callback", "text": "Назад", "payload": "BACK_MAIN"}]]


def get_or_create_client(
    db: Session,
    max_chat_id: str,
    name: str = "Unknown",
    referral_code: Optional[str] = None,
) -> Client:
    client = db.query(Client).filter(Client.max_chat_id == max_chat_id).first()
    if client:
        if name and client.name != name:
            client.name = name
            db.commit()
            db.refresh(client)
        return client

    code = generate_referral_code()
    while db.query(Client).filter(Client.referral_code == code).first():
        code = generate_referral_code()

    referred_by_id = None
    if referral_code:
        inviter = db.query(Client).filter(Client.referral_code == referral_code).first()
        if inviter:
            referred_by_id = inviter.id

    client = Client(
        max_chat_id=max_chat_id,
        name=name or "Unknown",
        referral_code=code,
        referred_by_id=referred_by_id,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _sum_active_bonus(db: Session, client_id: int) -> float:
    now = datetime.utcnow()
    total = (
        db.query(func.coalesce(func.sum(BonusLedger.amount), 0.0))
        .filter(
            BonusLedger.client_id == client_id,
            BonusLedger.available_from <= now,
            (BonusLedger.expires_at.is_(None) | (BonusLedger.expires_at >= now)),
        )
        .scalar()
    )
    return round(float(total or 0.0), 2)


def get_client_balance(db: Session, client_id: int) -> float:
    return max(0.0, _sum_active_bonus(db, client_id))


def _spent_for_period(db: Session, client_id: int) -> float:
    since = datetime.utcnow() - timedelta(days=config.LOYALTY_PERIOD_DAYS)
    total = (
        db.query(func.coalesce(func.sum(Policy.premium_amount), 0.0))
        .filter(Policy.client_id == client_id, Policy.created_at >= since, Policy.status == "ACTIVE")
        .scalar()
    )
    return float(total or 0.0)


def get_loyalty_level(total_spent: float) -> str:
    level = "BRONZE"
    for name, data in config.LOYALTY_TIERS.items():
        if total_spent >= data["min_spent"] and config.LOYALTY_TIERS[level]["min_spent"] <= data["min_spent"]:
            level = name
    return level


def update_client_tier(db: Session, client_id: int) -> str:
    client = db.get(Client, client_id)
    if not client:
        raise ValueError("Клиент не найден")

    spent = _spent_for_period(db, client_id)
    client.total_spent_last_period = spent
    client.loyalty_level = get_loyalty_level(spent)
    db.commit()
    db.refresh(client)
    return client.loyalty_level


def request_withdrawal(db: Session, client_id: int, amount: float) -> WithdrawalRequest:
    if amount < config.CASHBACK_THRESHOLD:
        raise ValueError(f"Минимальный порог вывода {config.CASHBACK_THRESHOLD:.0f} руб.")

    balance = get_client_balance(db, client_id)
    if amount > balance:
        raise ValueError("Недостаточно бонусов для вывода")

    db.add(
        BonusLedger(
            client_id=client_id,
            amount=-round(amount, 2),
            entry_type="WITHDRAWAL_HOLD",
            description="Резервирование бонусов под вывод на карту",
            available_from=datetime.utcnow(),
            expires_at=None,
        )
    )

    request = WithdrawalRequest(client_id=client_id, amount=round(amount, 2), status="PENDING")
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def approve_withdrawal(db: Session, request_id: int) -> WithdrawalRequest:
    req = db.get(WithdrawalRequest, request_id)
    if not req:
        raise ValueError("Заявка не найдена")
    if req.status != "PENDING":
        raise ValueError("Заявка уже обработана")

    req.status = "APPROVED"
    req.processed_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return req


def create_broadcast(db: Session, title: str, message: str, only_with_referrals: bool = False) -> int:
    item = BroadcastLog(title=title, message=message, only_with_referrals=only_with_referrals)
    db.add(item)
    db.commit()
    db.refresh(item)

    query = db.query(Client)
    if only_with_referrals:
        query = query.filter(Client.referred_by_id.isnot(None))

    for client in query.all():
        send_max_notification(client.max_chat_id, message, buttons=get_main_menu_buttons())

    return item.id






