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
    apply_discount_to_policy,
    create_broadcast,
    generate_referral_link,
    get_client_balance,
    get_main_menu_buttons,
    get_or_create_client,
    get_products_menu_buttons,
    notify_owner,
    register_policy,
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


class DiscountIn(BaseModel):
    client_chat_id: str
    target_policy_type: str
    amount: float = Field(gt=0)


class WithdrawalIn(BaseModel):
    client_chat_id: str
    amount: float = Field(gt=0)


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


def build_welcome_text(client_name: str) -> str:
    return (
        f"Здравствуйте, {client_name}!\n\n"
        f"Вы попали в Центр страхования.\n"
        f"Здесь вы можете:\n"
        f"— узнать бонусный баланс\n"
        f"— получить реферальную ссылку\n"
        f"— оставить заявку на вывод бонусов\n"
        f"— выбрать интересующий вид страхования\n"
        f"— передать запрос менеджеру\n\n"
        f"Выберите нужное действие кнопками ниже."
    )


def build_products_text() -> str:
    return (
        "Выберите интересующий вид страхования:\n"
        "— ОСАГО\n"
        "— КАСКО\n"
        "— Ипотечное страхование\n"
        "— Страхование имущества\n"
        "— Страхование жизни\n"
        "— Страхование путешествий"
    )


def build_reply_for_action(db: Session, client: Client, action: str) -> tuple[str, list]:
    if action in {"/start", "start", "ACTION_START", "ACTION_MENU", "меню"}:
        return build_welcome_text(client.name), get_main_menu_buttons()

    if action in {"ACTION_HELP", "помощь"}:
        return config.MESSAGE_HELP, get_main_menu_buttons()

    if action in {"ACTION_BALANCE", "баланс"}:
        return f"Ваш текущий бонусный баланс: {get_client_balance(db, client.id):.2f} руб.", get_main_menu_buttons()

    if action in {"ACTION_LEVEL", "уровень"}:
        update_client_tier(db, client.id)
        db.refresh(client)
        return (
            f"Ваш уровень лояльности: {client.loyalty_level}.\n"
            f"Сумма оформленных полисов за период: {client.total_spent_last_period:.2f} руб.",
            get_main_menu_buttons(),
        )

    if action in {"ACTION_REFERRAL", "реферал", "/refer"}:
        return (
            f"Ваша персональная реферальная ссылка:\n{generate_referral_link(client)}\n\n"
            f"Отправьте её знакомым. Когда по вашей рекомендации оформят полис, вам начислится бонус.",
            get_main_menu_buttons(),
        )

    if action in {"ACTION_WITHDRAW_1000", "вывод 1000"}:
        try:
            req = request_withdrawal(db, client.id, 1000)
            return (
                f"Заявка на вывод #{req.id} создана на сумму {req.amount:.2f} руб.\n"
                f"Менеджер свяжется с вами после проверки.",
                get_main_menu_buttons(),
            )
        except Exception as exc:
            return f"Не удалось создать заявку на вывод: {exc}", get_main_menu_buttons()

    if action in {"ACTION_PRODUCTS", "тарифы"}:
        return build_products_text(), get_products_menu_buttons()

    if action == "PRODUCT_OSAGO":
        return (
            f"{config.PRODUCT_TEXTS['OSAGO']}\n\n"
            f"Если хотите оформить ОСАГО, нажмите «Связаться», и менеджер свяжется с вами.",
            get_products_menu_buttons(),
        )

    if action == "PRODUCT_KASKO":
        return (
            f"{config.PRODUCT_TEXTS['KASKO']}\n\n"
            f"Если хотите оформить КАСКО, нажмите «Связаться», и менеджер свяжется с вами.",
            get_products_menu_buttons(),
        )

    if action == "PRODUCT_MORTGAGE":
        return (
            f"{config.PRODUCT_TEXTS['MORTGAGE']}\n\n"
            f"Если хотите оформить ипотечное страхование, нажмите «Связаться».",
            get_products_menu_buttons(),
        )

    if action == "PRODUCT_PROPERTY":
        return (
            f"{config.PRODUCT_TEXTS['PROPERTY']}\n\n"
            f"Если хотите оформить страхование имущества, нажмите «Связаться».",
            get_products_menu_buttons(),
        )

    if action == "PRODUCT_LIFE":
        return (
            f"{config.PRODUCT_TEXTS['LIFE']}\n\n"
            f"Если хотите оформить страхование жизни, нажмите «Связаться».",
            get_products_menu_buttons(),
        )

    if action == "PRODUCT_TRAVEL":
        return (
            f"{config.PRODUCT_TEXTS['TRAVEL']}\n\n"
            f"Если хотите оформить страхование путешествий, нажмите «Связаться».",
            get_products_menu_buttons(),
        )

    if action in {"ACTION_CONTACT_MANAGER", "связаться"}:
        notify_owner(
            f"Новый запрос на связь с менеджером.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Действие: запрос связи"
        )
        return (
            "Ваш запрос передан менеджеру.\n"
            "С вами свяжутся по вашему обращению.",
            get_main_menu_buttons(),
        )

    if action.startswith("вывод"):
        try:
            amount = float(action.split()[1])
            req = request_withdrawal(db, client.id, amount)
            return (
                f"Заявка на вывод #{req.id} создана на сумму {req.amount:.2f} руб.",
                get_main_menu_buttons(),
            )
        except Exception as exc:
            return f"Не удалось создать заявку на вывод: {exc}", get_main_menu_buttons()

    return (
        "Команда не распознана.\n\n"
        + config.MESSAGE_HELP,
        get_main_menu_buttons(),
    )


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
            f"Нажатие кнопки в боте.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Нажал: {callback_payload}"
        )

        reply, buttons = build_reply_for_action(db, client, callback_payload)

        if callback_id:
            answer_callback(callback_id, "Принято")

        send_max_notification(target_id, reply, buttons=buttons)
        return {"status": "ok", "kind": "callback", "reply": reply}

    target_id, user_name, text, start_payload = extract_message_data(payload)

    if not target_id:
        return {"status": "ignored", "reason": "target_id not found"}

    client = get_or_create_client(db, target_id, user_name, start_payload)

    incoming_action = text or "/start"

    notify_owner(
        f"Новое сообщение в боте.\n"
        f"Клиент: {client.name}\n"
        f"user_id: {client.max_chat_id}\n"
        f"Сообщение: {incoming_action}"
    )

    reply, buttons = build_reply_for_action(db, client, incoming_action)
    send_max_notification(target_id, reply, buttons=buttons)

    return {"status": "ok", "kind": "message", "reply": reply}


@app.post("/admin/policies", dependencies=[Depends(require_admin)])
def admin_register_policy(payload: PolicyIn, db: Session = Depends(get_db)):
    client = get_or_create_client(db, payload.client_chat_id, payload.client_name, payload.referral_code)
    referral_source_client_id = client.referred_by_id if client.referred_by_id else None

    policy = register_policy(
        db=db,
        client_id=client.id,
        policy_type=payload.policy_type,
        premium_amount=payload.premium_amount,
        start_date=payload.start_date,
        end_date=payload.end_date,
        referral_source_client_id=referral_source_client_id,
    )

    balance = get_client_balance(db, client.id)

    send_max_notification(
        client.max_chat_id,
        (
            f"Вам начислен бонус за полис {payload.policy_type.upper()}.\n"
            f"Сумма бонуса: {policy.bonus_amount:.2f} руб.\n"
            f"Текущий баланс: {balance:.2f} руб."
        ),
        buttons=get_main_menu_buttons(),
    )

    notify_owner(
        f"Менеджер зарегистрировал полис.\n"
        f"Клиент: {client.name}\n"
        f"user_id: {client.max_chat_id}\n"
        f"Полис: {payload.policy_type.upper()}\n"
        f"Сумма: {payload.premium_amount:.2f}"
    )

    return {
        "policy_id": policy.id,
        "bonus_amount": policy.bonus_amount,
        "client_balance": balance,
        "client_level": db.get(Client, client.id).loyalty_level,
    }


@app.post("/admin/discounts/apply", dependencies=[Depends(require_admin)])
def admin_apply_discount(payload: DiscountIn, db: Session = Depends(get_db)):
    client = get_or_create_client(db, payload.client_chat_id)
    amount = apply_discount_to_policy(db, client.id, payload.target_policy_type, payload.amount)

    send_max_notification(
        client.max_chat_id,
        f"С вашего бонусного счёта списано {amount:.2f} руб. на оформление полиса {payload.target_policy_type.upper()}.",
        buttons=get_main_menu_buttons(),
    )

    return {
        "applied_amount": amount,
        "balance": get_client_balance(db, client.id),
    }


@app.post("/admin/withdrawals", dependencies=[Depends(require_admin)])
def admin_create_withdrawal(payload: WithdrawalIn, db: Session = Depends(get_db)):
    client = get_or_create_client(db, payload.client_chat_id)
    req = request_withdrawal(db, client.id, payload.amount)

    send_max_notification(
        client.max_chat_id,
        f"Ваша заявка на вывод #{req.id} создана на сумму {req.amount:.2f} руб.",
        buttons=get_main_menu_buttons(),
    )

    return {"request_id": req.id, "status": req.status, "amount": req.amount}


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


@app.post("/admin/broadcasts", dependencies=[Depends(require_admin)])
def admin_broadcast(payload: BroadcastIn, db: Session = Depends(get_db)):
    log_id = create_broadcast(db, payload.title, payload.message, payload.only_with_referrals)
    return {"broadcast_id": log_id}




