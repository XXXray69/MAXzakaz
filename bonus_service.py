from __future__ import annotations

import secrets
from datetime import datetime
from typing import Optional

import requests
from sqlalchemy.orm import Session

import config
from models import Client, ReferralEvent


def _max_headers() -> dict:
    return {
        "Authorization": config.MAX_BOT_TOKEN.strip(),
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


def get_main_menu_buttons() -> list:
    return [
        [{"type": "message", "text": "Заказать услугу", "payload": "Заказать услугу"}],
        [{"type": "message", "text": "Реферальная программа", "payload": "Реферальная программа"}],
    ]


def get_owner_referral_buttons(event_id: int) -> list:
    return [
        [{"type": "message", "text": f"Подтвердить {event_id}", "payload": f"Подтвердить {event_id}"}],
        [{"type": "message", "text": f"Отменить {event_id}", "payload": f"Отменить {event_id}"}],
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
    if referral_code:
        inviter = db.query(Client).filter(Client.referral_code == referral_code).first()
        if inviter:
            referred_by_id = inviter.id

    client = Client(
        max_chat_id=str(max_chat_id),
        name=name or "Unknown",
        referral_code=code,
        referred_by_id=referred_by_id,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def create_referral_event(db: Session, inviter_client_id: int, referred_client_id: int) -> ReferralEvent:
    existing = (
        db.query(ReferralEvent)
        .filter(
            ReferralEvent.inviter_client_id == inviter_client_id,
            ReferralEvent.referred_client_id == referred_client_id,
            ReferralEvent.status == "PENDING",
        )
        .first()
    )
    if existing:
        return existing

    event = ReferralEvent(
        inviter_client_id=inviter_client_id,
        referred_client_id=referred_client_id,
        status="PENDING",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def approve_referral_event(db: Session, event_id: int) -> ReferralEvent:
    event = db.get(ReferralEvent, event_id)
    if not event:
        raise ValueError("Реферальное событие не найдено")
    if event.status != "PENDING":
        raise ValueError("Событие уже обработано")

    event.status = "APPROVED"
    event.processed_at = datetime.utcnow()
    db.commit()
    db.refresh(event)
    return event


def cancel_referral_event(db: Session, event_id: int) -> ReferralEvent:
    event = db.get(ReferralEvent, event_id)
    if not event:
        raise ValueError("Реферальное событие не найдено")
    if event.status != "PENDING":
        raise ValueError("Событие уже обработано")

    event.status = "CANCELLED"
    event.processed_at = datetime.utcnow()
    db.commit()
    db.refresh(event)
    return event














