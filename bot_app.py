from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import config
from bonus_service import (
    answer_callback,
    approve_withdrawal,
    create_broadcast,
    generate_referral_link,
    get_back_buttons,
    get_client_balance,
    get_consult_buttons,
    get_main_menu_buttons,
    get_or_create_client,
    get_products_buttons,
    notify_owner,
    request_withdrawal,
    send_max_notification,
    update_client_tier,
)
from models import Client, WithdrawalRequest, get_db, initialize_db

app = FastAPI(title="MAX Loyalty Bot")
initialize_db()

HELP_WAITING_USERS: set[str] = set()
LAST_SELECTED_PRODUCT: dict[str, str] = {}


class BroadcastIn(BaseModel):
    title: str
    message: str
    only_with_referrals: bool = False


def require_admin(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {config.ADMIN_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Неверный ADMIN_TOKEN")


def _extract_text_from_message(message: dict[str, Any]) -> str:
    candidates = [
        message.get("text"),
        message.get("payload"),
        (message.get("body") or {}).get("text"),
        (message.get("body") or {}).get("payload"),
        (message.get("message") or {}).get("text"),
        (message.get("message") or {}).get("payload"),
    ]

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def extract_message_data(payload: dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    update_type = payload.get("update_type")

    if update_type == "bot_started":
        user = payload.get("user") or {}
        target_id = str(
            user.get("user_id")
            or payload.get("chat_id")
            or payload.get("user_id")
            or ""
        )
        user_name = user.get("name") or user.get("username") or "Unknown"
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
    user_name = sender.get("name") or sender.get("username") or "Unknown"

    text = _extract_text_from_message(message)
    if not text and isinstance(payload.get("text"), str):
        text = payload.get("text", "").strip()

    return target_id, user_name, text, None


def extract_callback_data(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    callback = payload.get("callback") or {}
    message = callback.get("message") or {}
    sender = callback.get("sender") or {}

    callback_id = str(callback.get("callback_id") or "")
    callback_payload = str(callback.get("payload") or "")
    target_id = str(
        sender.get("user_id")
        or message.get("user_id")
        or message.get("chat_id")
        or ""
    )
    user_name = sender.get("name") or sender.get("username") or "Unknown"

    return callback_id, callback_payload, target_id, user_name


def welcome_text(client_name: str) -> str:
    return (
        f"Здравствуйте, {client_name}!\n\n"
        f"Вы попали в Центр страхования.\n"
        f"Здесь вы можете:\n"
        f"— посмотреть бонусный баланс\n"
        f"— узнать уровень лояльности\n"
        f"— получить реферальную ссылку\n"
        f"— оставить заявку на вывод бонусов\n"
        f"— выбрать интересующий вид страхования\n"
        f"— передать запрос владельцу/менеджеру\n\n"
        f"Выберите нужное действие кнопками ниже."
    )


def route_action(db: Session, client: Client, action: str) -> tuple[str, list]:
    action = (action or "").strip()

    if action in {"/start", "start"}:
        return welcome_text(client.name), get_main_menu_buttons()

    if action == "Баланс":
        return (
            f"Ваш баланс: {get_client_balance(db, client.id):.2f} руб.",
            get_back_buttons("Назад"),
        )

    if action == "Уровень":
        update_client_tier(db, client.id)
        db.refresh(client)
        return (
            f"Ваш уровень: {client.loyalty_level}.\n"
            f"Сумма оформленных полисов за период: {client.total_spent_last_period:.2f} руб.",
            get_back_buttons("Назад"),
        )

    if action == "Реферал":
        return (
            f"Ваша реферальная ссылка:\n{generate_referral_link(client)}\n\n"
            f"Отправьте её знакомым. Если по вашей рекомендации оформят полис, вам начислится бонус.",
            get_back_buttons("Назад"),
        )

    if action == "Вывод 1000":
        try:
            req = request_withdrawal(db, client.id, 1000)
            return (
                f"Заявка на вывод создана.\n"
                f"Номер: {req.id}\n"
                f"Сумма: {req.amount:.2f} руб.",
                get_back_buttons("Назад"),
            )
        except Exception as exc:
            return (
                f"Не удалось создать заявку на вывод: {exc}",
                get_back_buttons("Назад"),
            )

    if action == "Тарифы":
        return "Выберите вид страхования:", get_products_buttons()

    if action in config.PRODUCT_TEXTS:
        LAST_SELECTED_PRODUCT[client.max_chat_id] = action
        return config.PRODUCT_TEXTS[action], get_consult_buttons("Тарифы")

    if action == "Заказать консультацию":
        product_name = LAST_SELECTED_PRODUCT.get(client.max_chat_id, "не указан")
        notify_owner(
            f"Запрос консультации по тарифу.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Тариф: {product_name}"
        )
        return (
            "Спасибо за обращение! Наш менеджер свяжется с вами в ближайшее время.",
            get_main_menu_buttons(),
        )

    if action == "Связаться":
        notify_owner(
            f"Запрос менеджеру.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Действие: Связаться"
        )
        return (
            "Ваш запрос передан владельцу бота. С вами свяжутся.",
            get_back_buttons("Назад"),
        )

    if action == "Помощь":
        HELP_WAITING_USERS.add(client.max_chat_id)
        return (
            "Напишите, какой у вас вопрос, и наш менеджер ответит вам в ближайшее время.",
            get_back_buttons("Назад"),
        )

    if action in {"Назад", "Вернуться назад"}:
        HELP_WAITING_USERS.discard(client.max_chat_id)
        return welcome_text(client.name), get_main_menu_buttons()

    return "Команда не распознана.", get_main_menu_buttons()


@app.get("/")
def root():
    return {"status": "ok", "service": "MAX loyalty bot"}


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

        reply, buttons = route_action(db, client, callback_payload)

        if callback_id:
            answer_callback(callback_id, "Принято")

        send_max_notification(target_id, reply, buttons=buttons)
        return {"status": "ok", "kind": "callback", "action": callback_payload}

    target_id, user_name, text, start_payload = extract_message_data(payload)

    if not target_id:
        return {"status": "ignored", "reason": "target_id not found"}

    client = get_or_create_client(db, target_id, user_name, start_payload)

    if client.max_chat_id in HELP_WAITING_USERS and text not in {"Назад", "Вернуться назад", "Помощь"}:
        notify_owner(
            f"Сообщение в раздел помощи.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Вопрос: {text}"
        )
        HELP_WAITING_USERS.discard(client.max_chat_id)
        send_max_notification(client.max_chat_id, "Сообщение отправлено.", buttons=get_main_menu_buttons())
        return {
            "status": "ok",
            "kind": "help_message",
            "text_received": text,
        }

    notify_owner(
        f"Новое сообщение.\n"
        f"Клиент: {client.name}\n"
        f"user_id: {client.max_chat_id}\n"
        f"Текст: {text}"
    )

    reply, buttons = route_action(db, client, text or "/start")
    send_max_notification(target_id, reply, buttons=buttons)

    return {
        "status": "ok",
        "kind": "message",
        "text_received": text,
    }


@app.post("/admin/broadcasts", dependencies=[Depends(require_admin)])
def admin_broadcast(payload: BroadcastIn, db: Session = Depends(get_db)):
    log_id = create_broadcast(db, payload.title, payload.message, payload.only_with_referrals)
    return {"broadcast_id": log_id}


@app.get("/admin/withdrawals/pending", dependencies=[Depends(require_admin)])
def admin_pending_withdrawals(db: Session = Depends(get_db)):
    rows = db.query(WithdrawalRequest).filter(WithdrawalRequest.status == "PENDING").all()
    return [
        {
            "request_id": row.id,
            "client_id": row.client_id,
            "amount": row.amount,
            "requested_at": row.requested_at.isoformat(),
        }
        for row in rows
    ]


@app.post("/admin/withdrawals/{request_id}/approve", dependencies=[Depends(require_admin)])
def admin_approve_withdrawal(request_id: int, db: Session = Depends(get_db)):
    req = approve_withdrawal(db, request_id)
    return {
        "request_id": req.id,
        "status": req.status,
        "processed_at": req.processed_at.isoformat(),
    }


















