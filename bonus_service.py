from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

import config
from models import BonusLedger, BroadcastLog, Client, Policy, WithdrawalRequest


def send_max_notification(max_chat_id: str, message: str) -> None:
    """Заглушка отправки сообщений в MAX.

    Для реального проекта сюда подключается HTTP API MAX.
    """
    print(f"[MAX -> {max_chat_id}] {message}")


def generate_referral_code() -> str:
    return f"REF{secrets.token_hex(4).upper()}"


def generate_referral_link(client: Client) -> str:
    return f"https://max.ru/{config.MAX_BOT_USERNAME}?start={client.referral_code}"


def get_or_create_client(db: Session, max_chat_id: str, name: str = "Unknown", referral_code: Optional[str] = None) -> Client:
    client = db.query(Client).filter(Client.max_chat_id == max_chat_id).first()
    if client:
        if name and client.name != name:
            client.name = name
            db.commit()
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
    earned = (
        db.query(func.coalesce(func.sum(BonusLedger.amount), 0.0))
        .filter(
            BonusLedger.client_id == client_id,
            BonusLedger.available_from <= now,
            (BonusLedger.expires_at.is_(None) | (BonusLedger.expires_at >= now)),
        )
        .scalar()
    )
    return round(float(earned or 0.0), 2)


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
    return client.loyalty_level


def register_policy(
    db: Session,
    client_id: int,
    policy_type: str,
    premium_amount: float,
    start_date: datetime,
    end_date: datetime,
    referral_source_client_id: Optional[int] = None,
) -> Policy:
    policy_type = policy_type.upper()
    if end_date <= start_date:
        raise ValueError("Дата окончания должна быть позже даты начала")
    if premium_amount <= 0:
        raise ValueError("Сумма полиса должна быть больше нуля")

    rate = config.POLICY_BONUS_RATES.get(policy_type, 0.0)
    bonus_amount = round(premium_amount * rate, 2)

    policy = Policy(
        client_id=client_id,
        policy_type=policy_type,
        premium_amount=premium_amount,
        start_date=start_date,
        end_date=end_date,
        referral_source_client_id=referral_source_client_id,
        bonus_rate=rate,
        bonus_amount=bonus_amount,
    )
    db.add(policy)
    db.flush()

    if bonus_amount > 0:
        db.add(
            BonusLedger(
                client_id=client_id,
                amount=bonus_amount,
                entry_type="POLICY_BONUS",
                description=f"Бонус за полис {policy_type}",
                available_from=start_date,
                expires_at=end_date,
                policy_id=policy.id,
            )
        )

    if referral_source_client_id:
        ref_rate = config.REFERRAL_BONUS_RATES.get(policy_type, 0.0)
        ref_bonus = round(premium_amount * ref_rate, 2)
        if ref_bonus > 0:
            db.add(
                BonusLedger(
                    client_id=referral_source_client_id,
                    amount=ref_bonus,
                    entry_type="REFERRAL_BONUS",
                    description=f"Реферальный бонус за полис {policy_type}",
                    available_from=start_date,
                    expires_at=end_date,
                    policy_id=policy.id,
                )
            )

    db.commit()
    db.refresh(policy)
    update_client_tier(db, client_id)
    return policy


def apply_discount_to_policy(db: Session, client_id: int, target_policy_type: str, requested_amount: float) -> float:
    policy_type = target_policy_type.upper()
    if policy_type not in config.VOLUNTARY_POLICY_TYPES:
        raise ValueError("Бонусы можно списывать только на добровольные виды страхования")
    if requested_amount <= 0:
        raise ValueError("Сумма списания должна быть больше нуля")

    balance = get_client_balance(db, client_id)
    amount = min(balance, requested_amount)
    if amount <= 0:
        return 0.0

    db.add(
        BonusLedger(
            client_id=client_id,
            amount=-round(amount, 2),
            entry_type="DISCOUNT_APPLIED",
            description=f"Списание бонусов на полис {policy_type}",
            available_from=datetime.utcnow(),
            expires_at=None,
        )
    )
    db.commit()
    return round(amount, 2)


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

    query = db.query(Client)
    if only_with_referrals:
        query = query.filter(Client.referred_by_id.isnot(None))

    for client in query.all():
        send_max_notification(client.max_chat_id, message)
    return item.id
