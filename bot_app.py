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


def build_reply_for_text(db: Session, client: Client, text: str) -> str:
    text_lower = text.strip().lower()

    if text_lower in {"/start", "start", "меню"}:
        return (
            f"Здравствуйте, {client.name}.\n"
            f"Вы подключены к программе лояльности.\n"
            f"Ваш уровень: {client.loyalty_level}\n\n"
            f"{config.MESSAGE_HELP}"
        )

    if text_lower == "баланс":
        return f"Ваш активный бонусный баланс: {get_client_balance(db, client.id):.2f} руб."

    if text_lower == "уровень":
        update_client_tier(db, client.id)
        db.refresh(client)
        return (
            f"Ваш уровень: {client.loyalty_level}.\n"
            f"Сумма оформленных полисов за период: {client.total_spent_last_period:.2f} руб."
        )

    if text_lower in {"реферал", "/refer"}:
        return f"Ваша реферальная ссылка: {generate_referral_link(client)}"

    if text_lower.startswith("вывод"):
        try:
            amount = float(text.split()[1])
            req = request_withdrawal(db, client.id, amount)
            return f"Заявка на вывод #{req.id} создана на сумму {req.amount:.2f} руб."
        except Exception as exc:
            return f"Ошибка: {exc}"

    if text_lower == "помощь":
        return config.MESSAGE_HELP

    return "Команда не распознана.\n" + config.MESSAGE_HELP


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
        reply = build_reply_for_text(db, client, callback_payload)

        if callback_id:
            answer_callback(callback_id, "Обрабатываю")

        send_max_notification(target_id, reply, buttons=get_main_menu_buttons())
        return {"status": "ok", "kind": "callback", "reply": reply}

    target_id, user_name, text, start_payload = extract_message_data(payload)

    if not target_id:
        return {"status": "ignored", "reason": "target_id not found"}

    client = get_or_create_client(db, target_id, user_name, start_payload)

    if not text:
        text = "/start"

    reply = build_reply_for_text(db, client, text)
    send_max_notification(target_id, reply, buttons=get_main_menu_buttons())

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


