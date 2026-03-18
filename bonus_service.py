from __future__ import annotations

import re
import secrets
import string
from datetime import datetime
from typing import Optional

import requests
from sqlalchemy.orm import Session

import config
from models import Client, ReferralEvent, ServiceRequest


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
            params={"user_id": str(max_user_id)},
            json=body,
            timeout=20,
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
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[MAX callback answer error] callback_id={callback_id} error={exc}")
        if response is not None:
            print(f"[MAX callback answer body] {response.text}")


def notify_owner(text: str, buttons: Optional[list] = None) -> None:
    if not config.OWNER_USER_ID:
        print(f"[OWNER notify skipped] {text}")
        return
    send_max_notification(config.OWNER_USER_ID, text, buttons=buttons)


def generate_referral_code() -> str:
    return f"REF{secrets.token_hex(4).upper()}"


def generate_referral_link(client: Client) -> str:
    return f"https://max.ru/{config.MAX_BOT_USERNAME}?start={client.referral_code}"


def generate_request_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "#" + "".join(secrets.choice(chars) for _ in range(11))


def get_main_menu_buttons(client: Client) -> list:
    rows = [
        [{"type": "message", "text": "Заказать услугу", "payload": "Заказать услугу"}],
        [{"type": "message", "text": "Оформить скидку для друга", "payload": "Оформить скидку для друга"}],
        [
            {"type": "message", "text": "Баланс", "payload": "Баланс"},
            {"type": "message", "text": "Списать бонус", "payload": "Списать бонус"},
        ],
    ]

    if client.referred_by_id and not client.discount_request_used:
        rows.append([{"type": "message", "text": "Хочу скидку", "payload": "Хочу скидку"}])

    return rows


def get_owner_reward_buttons(request_id: int) -> list:
    return [
        [{"type": "message", "text": f"Отблагодарить реферала {request_id}", "payload": f"Отблагодарить реферала {request_id}"}],
        [{"type": "message", "text": f"Отменить {request_id}", "payload": f"Отменить {request_id}"}],
    ]


def get_or_create_client(
    db: Session,
    max_chat_id: str,
    name: str = "Unknown",
    referral_code: Optional[str] = None,
) -> Client:
    client = db.query(Client).filter(Client.max_chat_id == str(max_chat_id)).first()
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
    referral_locked = False

    if referral_code:
        inviter = db.query(Client).filter(Client.referral_code == referral_code).first()
        if inviter:
            referred_by_id = inviter.id
            referral_locked = True

    client = Client(
        max_chat_id=str(max_chat_id),
        name=name or "Unknown",
        referral_code=code,
        referred_by_id=referred_by_id,
        referral_locked=referral_locked,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def ensure_referral_locked(db: Session, client: Client, start_payload: Optional[str]) -> Client:
    if client.referral_locked:
        return client

    if not start_payload:
        return client

    inviter = db.query(Client).filter(Client.referral_code == start_payload).first()
    if not inviter:
        return client

    if inviter.id == client.id:
        return client

    client.referred_by_id = inviter.id
    client.referral_locked = True
    db.commit()
    db.refresh(client)
    return client


def get_or_create_referral_event(db: Session, inviter_client_id: int, referred_client_id: int) -> ReferralEvent:
    existing = (
        db.query(ReferralEvent)
        .filter(ReferralEvent.referred_client_id == referred_client_id)
        .first()
    )
    if existing:
        return existing

    event = ReferralEvent(
        inviter_client_id=inviter_client_id,
        referred_client_id=referred_client_id,
        status="VISITED",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def mark_referral_requested(db: Session, referred_client_id: int, request_code: str) -> Optional[ReferralEvent]:
    event = (
        db.query(ReferralEvent)
        .filter(ReferralEvent.referred_client_id == referred_client_id)
        .first()
    )
    if not event:
        return None

    event.status = "REQUESTED"
    event.note = request_code
    event.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(event)
    return event


def create_service_request(
    db: Session,
    request_type: str,
    client: Client,
    contact_text: str,
    referrer_client_id: Optional[int] = None,
    bonus_amount: Optional[float] = None,
) -> ServiceRequest:
    code = generate_request_code()
    while db.query(ServiceRequest).filter(ServiceRequest.code == code).first():
        code = generate_request_code()

    request = ServiceRequest(
        code=code,
        request_type=request_type,
        client_id=client.id,
        referrer_client_id=referrer_client_id,
        account_name=client.name,
        client_max_chat_id=client.max_chat_id,
        contact_text=contact_text,
        bonus_amount=bonus_amount,
        status="PENDING",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def get_request_by_id(db: Session, request_id: int) -> Optional[ServiceRequest]:
    return db.get(ServiceRequest, request_id)


def cancel_request(db: Session, request_id: int) -> ServiceRequest:
    request = db.get(ServiceRequest, request_id)
    if not request:
        raise ValueError("Заявка не найдена")

    request.status = "CANCELLED"
    request.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(request)
    return request


def reward_referrer(db: Session, request_id: int, amount: float) -> tuple[ServiceRequest, Client]:
    request = db.get(ServiceRequest, request_id)
    if not request:
        raise ValueError("Заявка не найдена")

    if request.status == "CANCELLED":
        raise ValueError("Заявка уже отменена")

    if not request.referrer_client_id:
        raise ValueError("У заявки нет реферала")

    referrer = db.get(Client, request.referrer_client_id)
    if not referrer:
        raise ValueError("Реферал не найден")

    referrer.balance = float(referrer.balance or 0) + float(amount)

    request.status = "REWARDED"
    request.bonus_amount = float(amount)
    request.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(request)
    db.refresh(referrer)
    return request, referrer


def parse_phone_and_amount(text: str) -> tuple[str, Optional[float]]:
    match = re.search(r"\((\d+(?:[.,]\d+)?)\)", text)
    if not match:
        return text.strip(), None

    raw = match.group(1).replace(",", ".")
    amount = float(raw)
    clean_text = re.sub(r"\(\d+(?:[.,]\d+)?\)", "", text).strip()
    return clean_text, amount














