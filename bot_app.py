from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

import config
from bonus_service import (
    answer_callback,
    approve_referral_event,
    cancel_referral_event,
    create_referral_event,
    generate_referral_link,
    get_main_menu_buttons,
    get_or_create_client,
    get_owner_referral_buttons,
    notify_owner,
    send_max_notification,
)
from models import Client, get_db, initialize_db

APP_VERSION = "service-request-v2"

app = FastAPI(title="MAX Referral Bot")
initialize_db()

WAITING_SERVICE_REQUEST: set[str] = set()


def _extract_text_from_message(message: dict[str, Any]) -> str:
    body = message.get("body") or {}
    return (
        message.get("text")
        or body.get("text")
        or message.get("payload")
        or body.get("payload")
        or ""
    ).strip()


def extract_message_data(payload: dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    update_type = payload.get("update_type")

    if update_type == "bot_started":
        user = payload.get("user") or {}
        target_id = str(user.get("user_id") or payload.get("chat_id") or payload.get("user_id") or "")
        user_name = (
            user.get("name")
            or f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            or user.get("username")
            or "Unknown"
        )
        text = "/start"
        start_payload = payload.get("payload")
        return target_id, user_name, text, start_payload

    message = payload.get("message") or {}
    sender = message.get("sender") or {}

    target_id = str(
        sender.get("user_id")
        or message.get("user_id")
        or message.get("chat_id")
        or payload.get("user_id")
        or ""
    )

    user_name = (
        sender.get("name")
        or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
        or sender.get("username")
        or "Unknown"
    )

    text = _extract_text_from_message(message)
    return target_id, user_name, text, None


def extract_callback_data(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    callback = payload.get("callback") or {}
    message = callback.get("message") or {}
    sender = callback.get("sender") or {}

    callback_id = str(callback.get("callback_id") or "")
    callback_payload = str(callback.get("payload") or "")
    target_id = str(sender.get("user_id") or message.get("user_id") or message.get("chat_id") or "")
    user_name = (
        sender.get("name")
        or f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip()
        or sender.get("username")
        or "Unknown"
    )

    return callback_id, callback_payload, target_id, user_name


def welcome_text(client_name: str) -> str:
    return (
        f"Здравствуйте, {client_name}!\n\n"
        f"Добро пожаловать в наш страховой сервис.\n"
        f"Выберите нужное действие кнопками ниже."
    )


def handle_owner_action(db: Session, text: str) -> Optional[str]:
    if text.startswith("Подтвердить "):
        try:
            event_id = int(text.split(" ", 1)[1].strip())
            event = approve_referral_event(db, event_id)
            inviter = db.get(Client, event.inviter_client_id)

            if inviter:
                send_max_notification(
                    inviter.max_chat_id,
                    "Ваш друг перешёл по нашей реферальной ссылке и оформил услугу у нашего специалиста.",
                    buttons=get_main_menu_buttons(),
                )

            return f"Реферальное обращение #{event.id} подтверждено."
        except Exception as exc:
            return f"Ошибка подтверждения: {exc}"

    if text.startswith("Отменить "):
        try:
            event_id = int(text.split(" ", 1)[1].strip())
            event = cancel_referral_event(db, event_id)
            return f"Реферальное обращение #{event.id} отменено."
        except Exception as exc:
            return f"Ошибка отмены: {exc}"

    return None


def route_action(client: Client, action: str) -> tuple[str, Optional[list]]:
    action = (action or "").strip()

    if action in {"/start", "start"}:
        return welcome_text(client.name), get_main_menu_buttons()

    if action == "Заказать услугу":
        WAITING_SERVICE_REQUEST.add(client.max_chat_id)
        return (
            "Отправьте, пожалуйста, свои данные для обратной связи (ФИО, номер телефона).",
            None,
        )

    if action == "Реферальная программа":
        link = generate_referral_link(client)
        return (
            f"Ваша персональная реферальная ссылка:\n{link}\n\n"
            f"Отправьте её другу. Если он обратится к нашему специалисту и заявка будет подтверждена, "
            f"мы зафиксируем это в системе.",
            get_main_menu_buttons(),
        )

    return welcome_text(client.name), get_main_menu_buttons()


@app.get("/")
def root():
    return {"status": "ok", "service": "MAX referral bot", "version": APP_VERSION}


@app.post("/webhook")
def webhook(
    payload: dict[str, Any],
    x_max_bot_api_secret: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if config.WEBHOOK_SECRET and x_max_bot_api_secret != config.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    print("[WEBHOOK PAYLOAD]", json.dumps(payload, ensure_ascii=False))

    update_type = payload.get("update_type")

    if update_type == "message_callback":
        callback_id, callback_payload, target_id, user_name = extract_callback_data(payload)

        if not target_id:
            return {"status": "ignored", "reason": "target_id not found"}

        client = get_or_create_client(db, target_id, user_name)

        owner_result = handle_owner_action(db, callback_payload)
        if owner_result:
            if callback_id:
                answer_callback(callback_id, "Принято")
            send_max_notification(target_id, owner_result, buttons=get_main_menu_buttons())
            return {"status": "ok", "kind": "owner_callback"}

        reply, buttons = route_action(client, callback_payload)

        if callback_id:
            answer_callback(callback_id, "Принято")

        send_max_notification(target_id, reply, buttons=buttons)
        return {"status": "ok", "kind": "callback"}

    target_id, user_name, text, start_payload = extract_message_data(payload)

    if not target_id:
        return {"status": "ignored", "reason": "target_id not found"}

    client = get_or_create_client(db, target_id, user_name, start_payload)

    owner_result = handle_owner_action(db, text)
    if owner_result and target_id == config.OWNER_USER_ID:
        send_max_notification(target_id, owner_result, buttons=get_main_menu_buttons())
        return {"status": "ok", "kind": "owner_action"}

    if start_payload and client.referred_by_id:
        inviter = db.get(Client, client.referred_by_id)
        if inviter:
            event = create_referral_event(db, inviter.id, client.id)

            notify_owner(
                f"Пользователь воспользовался реферальной программой.\n"
                f"Новый пользователь: {client.name}\n"
                f"user_id: {client.max_chat_id}\n"
                f"Пригласил: {inviter.name}\n"
                f"inviter_user_id: {inviter.max_chat_id}\n"
                f"Событие ID: {event.id}",
                buttons=get_owner_referral_buttons(event.id),
            )

        send_max_notification(
            client.max_chat_id,
            "Здравствуйте! Вы воспользовались нашей реферальной программой. "
            "Вам одобрена скидка на услугу страхования от нашего специалиста. "
            "Ожидайте, наш менеджер свяжется с вами в ближайшее время.",
            buttons=get_main_menu_buttons(),
        )
        return {"status": "ok", "kind": "referral_start"}

    if client.max_chat_id in WAITING_SERVICE_REQUEST:
        if text in {"/start", "start"}:
            WAITING_SERVICE_REQUEST.discard(client.max_chat_id)
            reply, buttons = route_action(client, "/start")
            send_max_notification(target_id, reply, buttons=buttons)
            return {"status": "ok", "kind": "reset_to_start"}

        if text == "Заказать услугу":
            send_max_notification(
                target_id,
                "Отправьте, пожалуйста, свои данные для обратной связи (ФИО, номер телефона).",
                buttons=None,
            )
            return {"status": "ok", "kind": "waiting_repeat"}

        if text == "Реферальная программа":
            WAITING_SERVICE_REQUEST.discard(client.max_chat_id)
            reply, buttons = route_action(client, "Реферальная программа")
            send_max_notification(target_id, reply, buttons=buttons)
            return {"status": "ok", "kind": "switch_to_referral"}

        WAITING_SERVICE_REQUEST.discard(client.max_chat_id)

        notify_owner(
            f"Новая заявка на услугу.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Сообщение клиента: {text}"
        )

        send_max_notification(
            client.max_chat_id,
            "Спасибо за обращение! Наш менеджер свяжется с вами в ближайшее время.",
            buttons=get_main_menu_buttons(),
        )
        return {"status": "ok", "kind": "service_request_sent"}

    reply, buttons = route_action(client, text or "/start")
    send_max_notification(target_id, reply, buttons=buttons)

    return {"status": "ok", "kind": "message"}




















