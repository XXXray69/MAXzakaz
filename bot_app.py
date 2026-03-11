from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from bonus_service import (
    answer_callback,
    approve_withdrawal,
    create_broadcast,
    generate_referral_link,
    get_back_to_main_buttons,
    get_client_balance,
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


class PolicyIn(BaseModel):
    client_chat_id: str
    client_name: str = "Unknown"
    policy_type: str
    premium_amount: float = Field(gt=0)
    start_date: datetime
    end_date: datetime
    referral_code: Optional[str] = None


class BroadcastIn(BaseModel):
    title: str
    message: str
    only_with_referrals: bool = False


def require_admin(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {config.ADMIN_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Неверный ADMIN_TOKEN")


def extract_message_data(payload: dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    message = payload.get("message") or {}
    sender = message.get("sender") or {}

    user_id = sender.get("user_id")
    chat_id = message.get("chat_id")

    target_id = str(user_id or chat_id or "")
    user_name = sender.get("name") or sender.get("username") or "Unknown"
    text = (message.get("text") or "").strip()

    start_payload = None
    if payload.get("update_type") == "bot_started":
        start_payload = payload.get("start_payload") or message.get("start_payload")

    return target_id, user_name, text, start_payload


def extract_callback_data(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    callback = payload.get("callback") or {}
    message = callback.get("message") or {}
    sender = callback.get("sender") or {}

    callback_id = str(callback.get("callback_id") or "")
    callback_payload = str(callback.get("payload") or "")

    user_id = sender.get("user_id")
    chat_id = message.get("chat_id")
    target_id = str(user_id or chat_id or "")

    user_name = sender.get("name") or sender.get("username") or "Unknown"
    return callback_id, callback_payload, target_id, user_name


def welcome_text(client_name: str) -> str:
    return (
        f"Здравствуйте, {client_name}!\n\n"
        f"Вы попали в Центр страхования.\n"
        f"Здесь можно:\n"
        f"— посмотреть бонусный баланс\n"
        f"— узнать уровень лояльности\n"
        f"— получить реферальную ссылку\n"
        f"— выбрать нужный вид страхования\n"
        f"— оставить запрос менеджеру\n\n"
        f"Выберите действие кнопками ниже."
    )


def products_text() -> str:
    return (
        "Выберите интересующий вид страхования:\n"
        "— ОСАГО\n"
        "— КАСКО\n"
        "— Ипотечное страхование\n"
        "— Страхование имущества\n"
        "— Страхование жизни\n"
        "— Страхование путешествий"
    )


def route_action(db: Session, client: Client, action: str) -> tuple[str, list]:
    if action in {"/start", "start", "BACK_MAIN"}:
        return welcome_text(client.name), get_main_menu_buttons()

    if action == "HELP":
        return (
            "Доступные действия:\n"
            "Баланс — ваш текущий баланс бонусов.\n"
            "Уровень — ваш текущий уровень лояльности.\n"
            "Реферал — ваша персональная ссылка.\n"
            "Вывод 1000 — заявка на вывод при наличии бонусов.\n"
            "Тарифы — список доступных видов страхования.\n"
            "Связаться — передать ваш запрос менеджеру.",
            get_back_to_main_buttons(),
        )

    if action == "BALANCE":
        return (f"Ваш баланс: {get_client_balance(db, client.id):.2f} руб.", get_back_to_main_buttons())

    if action == "LEVEL":
        update_client_tier(db, client.id)
        db.refresh(client)
        return (
            f"Ваш уровень: {client.loyalty_level}.\n"
            f"Сумма оформленных полисов за период: {client.total_spent_last_period:.2f} руб.",
            get_back_to_main_buttons(),
        )

    if action == "REFERRAL":
        return (
            "Ваша реферальная ссылка:\n"
            f"{generate_referral_link(client)}\n\n"
            "Отправьте её знакомым. Если по вашей рекомендации оформят полис, вам начислится бонус.",
            get_back_to_main_buttons(),
        )

    if action == "WITHDRAW_1000":
        try:
            req = request_withdrawal(db, client.id, 1000)
            return (
                f"Заявка на вывод создана.\n"
                f"Номер заявки: {req.id}\n"
                f"Сумма: {req.amount:.2f} руб.",
                get_back_to_main_buttons(),
            )
        except Exception as exc:
            return (f"Не удалось создать заявку на вывод: {exc}", get_back_to_main_buttons())

    if action == "PRODUCTS":
        return products_text(), get_products_buttons()

    if action == "PRODUCT_OSAGO":
        return (
            f"{config.PRODUCT_TEXTS['OSAGO']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_OSAGO"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action == "PRODUCT_KASKO":
        return (
            f"{config.PRODUCT_TEXTS['KASKO']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_KASKO"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action == "PRODUCT_MORTGAGE":
        return (
            f"{config.PRODUCT_TEXTS['MORTGAGE']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_MORTGAGE"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action == "PRODUCT_PROPERTY":
        return (
            f"{config.PRODUCT_TEXTS['PROPERTY']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_PROPERTY"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action == "PRODUCT_LIFE":
        return (
            f"{config.PRODUCT_TEXTS['LIFE']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_LIFE"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action == "PRODUCT_TRAVEL":
        return (
            f"{config.PRODUCT_TEXTS['TRAVEL']}\n\n"
            "Для расчёта и оформления нажмите «Связаться».",
            [
                [{"type": "callback", "text": "Связаться", "payload": "CONTACT_MANAGER_TRAVEL"}],
                [{"type": "callback", "text": "Назад", "payload": "PRODUCTS"}],
            ],
        )

    if action.startswith("CONTACT_MANAGER"):
        notify_owner(
            f"Запрос менеджеру.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Действие: {action}"
        )
        return (
            "Ваш запрос передан владельцу/менеджеру.\n"
            "С вами свяжутся в ближайшее время.",
            get_back_to_main_buttons(),
        )

    return ("Команда не распознана.", get_back_to_main_buttons())


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

    update_type = payload.get("update_type")

    if update_type == "message_callback":
        callback_id, callback_payload, target_id, user_name = extract_callback_data(payload)
        if not target_id:
            return {"status": "ignored", "reason": "target_id not found"}

        client = get_or_create_client(db, target_id, user_name)

        notify_owner(
            f"Нажатие кнопки.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Кнопка: {callback_payload}"
        )

        reply, buttons = route_action(db, client, callback_payload)

        if callback_id:
            answer_callback(callback_id, "Принято")

        send_max_notification(target_id, reply, buttons=buttons)
        return {"status": "ok", "kind": "callback", "reply": reply}

    target_id, user_name, text, start_payload = extract_message_data(payload)
    if not target_id:
        return {"status": "ignored", "reason": "target_id not found"}

    client = get_or_create_client(db, target_id, user_name, start_payload)

    incoming = text or "/start"

    notify_owner(
        f"Новое сообщение.\n"
        f"Клиент: {client.name}\n"
        f"user_id: {client.max_chat_id}\n"
        f"Текст: {incoming}"
    )

    if incoming.lower() in {"баланс", "уровень", "реферал", "помощь", "тарифы"}:
        mapping = {
            "баланс": "BALANCE",
            "уровень": "LEVEL",
            "реферал": "REFERRAL",
            "помощь": "HELP",
            "тарифы": "PRODUCTS",
        }
        incoming = mapping[incoming.lower()]
    elif incoming.lower().startswith("вывод"):
        incoming = "WITHDRAW_1000"
    elif incoming.lower() in {"/start", "start"}:
        incoming = "/start"

    reply, buttons = route_action(db, client, incoming)
    send_max_notification(target_id, reply, buttons=buttons)

    return {"status": "ok", "kind": "message", "reply": reply}







