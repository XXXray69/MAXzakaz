from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from bonus_service import (
    approve_withdrawal,
    apply_discount_to_policy,
    create_broadcast,
    generate_referral_link,
    get_client_balance,
    get_or_create_client,
    register_policy,
    request_withdrawal,
    send_max_notification,
    update_client_tier,
)
from models import Client, WithdrawalRequest, get_db, initialize_db

app = FastAPI(title="MAX Loyalty Bot")
initialize_db()


class MaxIncomingMessage(BaseModel):
    chat_id: str
    user_name: str = "Unknown"
    text: str
    start_payload: Optional[str] = None


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


class StartWebhookIn(BaseModel):
    webhook_url: str


def require_admin(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {config.ADMIN_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Неверный ADMIN_TOKEN")


@app.get("/")
def root():
    return {"status": "ok", "service": "MAX loyalty bot"}


@app.post("/webhook")
def webhook(message: MaxIncomingMessage, db: Session = Depends(get_db)):
    client = get_or_create_client(db, message.chat_id, message.user_name, message.start_payload)
    text = message.text.strip()
    text_lower = text.lower()

    if text_lower in {"/start", "start"}:
        reply = (
            f"Здравствуйте, {client.name}. Вы подключены к программе лояльности.\n"
            f"Ваш уровень: {client.loyalty_level}\n"
            f"{config.MESSAGE_HELP}"
        )
    elif text_lower == "баланс":
        reply = f"Ваш активный бонусный баланс: {get_client_balance(db, client.id):.2f} руб."
    elif text_lower == "уровень":
        update_client_tier(db, client.id)
        db.refresh(client)
        reply = (
            f"Ваш уровень: {client.loyalty_level}.\n"
            f"Сумма оформленных полисов за период: {client.total_spent_last_period:.2f} руб."
        )
    elif text_lower in {"реферал", "/refer"}:
        reply = f"Ваша реферальная ссылка: {generate_referral_link(client)}"
    elif text_lower.startswith("вывод"):
        try:
            amount = float(text.split()[1])
            req = request_withdrawal(db, client.id, amount)
            reply = f"Заявка на вывод #{req.id} создана на сумму {req.amount:.2f} руб."
        except Exception as exc:
            reply = f"Ошибка: {exc}"
    elif text_lower == "помощь":
        reply = config.MESSAGE_HELP
    else:
        reply = "Команда не распознана.\n" + config.MESSAGE_HELP

    send_max_notification(client.max_chat_id, reply)
    return {"status": "ok", "reply": reply}


@app.post("/admin/policies", dependencies=[Depends(require_admin)])
def admin_register_policy(payload: PolicyIn, db: Session = Depends(get_db)):
    client = get_or_create_client(db, payload.client_chat_id, payload.client_name, payload.referral_code)
    referral_source_client_id = None
    if client.referred_by_id:
        referral_source_client_id = client.referred_by_id
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
    return {"applied_amount": amount, "balance": get_client_balance(db, client.id)}


@app.post("/admin/withdrawals", dependencies=[Depends(require_admin)])
def admin_create_withdrawal(payload: WithdrawalIn, db: Session = Depends(get_db)):
    client = get_or_create_client(db, payload.client_chat_id)
    req = request_withdrawal(db, client.id, payload.amount)
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
    return {"request_id": req.id, "status": req.status, "processed_at": req.processed_at.isoformat()}


@app.post("/admin/broadcasts", dependencies=[Depends(require_admin)])
def admin_broadcast(payload: BroadcastIn, db: Session = Depends(get_db)):
    log_id = create_broadcast(db, payload.title, payload.message, payload.only_with_referrals)
    return {"broadcast_id": log_id}