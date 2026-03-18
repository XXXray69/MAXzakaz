from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

import config
from bonus_service import (
    answer_callback,
    cancel_request,
    create_service_request,
    ensure_referral_locked,
    generate_referral_link,
    get_main_menu_buttons,
    get_or_create_client,
    get_or_create_referral_event,
    get_owner_reward_buttons,
    get_request_by_id,
    mark_referral_requested,
    notify_owner,
    parse_phone_and_amount,
    reward_referrer,
    send_max_notification,
)
from models import Client, get_db, initialize_db

APP_VERSION = "service-request-v3"

app = FastAPI(title="MAX Referral Bot")
initialize_db()

WAITING_SERVICE_CONTACT: set[str] = set()
WAITING_DISCOUNT_CONTACT: set[str] = set()
WAITING_BONUS_SPEND: set[str] = set()

OWNER_WAITING_REWARD_AMOUNT: dict[str, int] = {}


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


def welcome_text(client: Client) -> str:
    return (
        f"Здравствуйте, {client.name}!\n\n"
        f"Добро пожаловать в наш страховой сервис.\n"
        f"Выберите нужное действие кнопками ниже."
    )


def owner_process_text(db: Session, owner_id: str, text: str) -> Optional[str]:
    waiting_request_id = OWNER_WAITING_REWARD_AMOUNT.get(owner_id)
    if waiting_request_id:
        try:
            amount = float(text.replace(",", ".").strip())
            if amount <= 0:
                raise ValueError("сумма должна быть больше нуля")

            request, referrer = reward_referrer(db, waiting_request_id, amount)
            OWNER_WAITING_REWARD_AMOUNT.pop(owner_id, None)

            send_max_notification(
                referrer.max_chat_id,
                f"Вы получаете бонус на страхование {amount:.2f} рублей.\n\n"
                f"Готовы списать и обратиться за услугой? Нажмите на кнопку «Списать бонус».",
                buttons=get_main_menu_buttons(referrer),
            )

            return (
                f"Сумма для скидки зачислена рефералу.\n"
                f"Реферал: {referrer.name}\n"
                f"user_id: {referrer.max_chat_id}\n"
                f"Заявка: {request.code}\n"
                f"Сумма: {amount:.2f} руб."
            )
        except Exception as exc:
            return f"Ошибка ввода суммы: {exc}"

    if text.startswith("Отблагодарить реферала "):
        try:
            request_id = int(text.split(" ", 2)[2].strip())
            request = get_request_by_id(db, request_id)
            if not request:
                return "Заявка не найдена"

            OWNER_WAITING_REWARD_AMOUNT[owner_id] = request_id
            return (
                f"Введите сумму зачисления для реферала по заявке {request.code}.\n"
                f"Только число, без ошибок."
            )
        except Exception as exc:
            return f"Ошибка: {exc}"

    if text.startswith("Отменить "):
        try:
            request_id = int(text.split(" ", 1)[1].strip())
            request = cancel_request(db, request_id)
            return f"Заявка {request.code} отменена."
        except Exception as exc:
            return f"Ошибка отмены: {exc}"

    return None


def route_action(client: Client, action: str) -> tuple[str, Optional[list]]:
    action = (action or "").strip()

    if action in {"/start", "start"}:
        return welcome_text(client), get_main_menu_buttons(client)

    if action == "Заказать услугу":
        WAITING_SERVICE_CONTACT.add(client.max_chat_id)
        return (
            "Пожалуйста, введите свои данные для обратной связи (ФИО, номер телефона).",
            None,
        )

    if action == "Оформить скидку для друга":
        link = generate_referral_link(client)
        return (
            "Пригласите по этой ссылке друга и получите бонус после того, "
            "как он приобретёт услугу у нашего специалиста.\n\n"
            f"{link}",
            get_main_menu_buttons(client),
        )

    if action == "Хочу скидку":
        if not client.referred_by_id:
            return ("Для вас нет активного реферального приглашения.", get_main_menu_buttons(client))
        if client.discount_request_used:
            return ("Вы уже использовали возможность оформить скидку.", get_main_menu_buttons(client))

        WAITING_DISCOUNT_CONTACT.add(client.max_chat_id)
        return (
            "Пожалуйста, введите свои данные для обратной связи (ФИО, номер телефона).",
            None,
        )

    if action == "Баланс":
        return (f"Ваш бонусный баланс: {float(client.balance or 0):.2f} руб.", get_main_menu_buttons(client))

    if action == "Списать бонус":
        if float(client.balance or 0) <= 0:
            return ("У вас пока нет бонусов для списания.", get_main_menu_buttons(client))

        WAITING_BONUS_SPEND.add(client.max_chat_id)
        return (
            "Напишите свои данные: ФИО, телефон (без скобок), "
            "а в скобках укажите сумму, которую хотите списать.\n\n"
            "Пример:\nИванов Иван, 79990000000 (500)",
            None,
        )

    return welcome_text(client), get_main_menu_buttons(client)


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
            return {"status": "ignored"}

        client = get_or_create_client(db, target_id, user_name)
        owner_reply = owner_process_text(db, target_id, callback_payload)
        if owner_reply:
            if callback_id:
                answer_callback(callback_id, "Принято")
            send_max_notification(target_id, owner_reply, buttons=get_main_menu_buttons(client))
            return {"status": "ok"}

        reply, buttons = route_action(client, callback_payload)
        if callback_id:
            answer_callback(callback_id, "Принято")
        send_max_notification(target_id, reply, buttons=buttons)
        return {"status": "ok"}

    target_id, user_name, text, start_payload = extract_message_data(payload)
    if not target_id:
        return {"status": "ignored"}

    client = get_or_create_client(db, target_id, user_name)
    client = ensure_referral_locked(db, client, start_payload)

    if target_id == config.OWNER_USER_ID:
        owner_reply = owner_process_text(db, target_id, text)
        if owner_reply:
            send_max_notification(target_id, owner_reply, buttons=get_main_menu_buttons(client))
            return {"status": "ok", "kind": "owner_text"}

    if start_payload and client.referred_by_id:
        event = get_or_create_referral_event(db, client.referred_by_id, client.id)

        if event.status == "VISITED" and event.note is None:
            inviter = db.get(Client, client.referred_by_id)
            if inviter:
                notify_owner(
                    f"Пользователь воспользовался реферальной системой.\n"
                    f"Клиент: {client.name}\n"
                    f"user_id: {client.max_chat_id}\n"
                    f"Реферал: {inviter.name}\n"
                    f"referrer_user_id: {inviter.max_chat_id}\n"
                    f"Пока кнопку «Хочу скидку» не нажимал."
                )
            event.note = "OWNER_NOTIFIED"
            db.commit()

        send_max_notification(
            client.max_chat_id,
            "Здравствуйте! Вы перешли по реферальной ссылке.\n"
            "Если хотите получить скидку, нажмите кнопку «Хочу скидку».",
            buttons=get_main_menu_buttons(client),
        )
        return {"status": "ok", "kind": "referral_visit"}

    if client.max_chat_id in WAITING_SERVICE_CONTACT:
        WAITING_SERVICE_CONTACT.discard(client.max_chat_id)

        request = create_service_request(
            db=db,
            request_type="SERVICE",
            client=client,
            contact_text=text,
        )

        notify_owner(
            f"Новая заявка на услугу.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Данные: {text}\n"
            f"Код заявки: {request.code}"
        )

        send_max_notification(
            client.max_chat_id,
            f"Спасибо за обращение! Наш менеджер свяжется с вами в ближайшее время.\n"
            f"Код вашей заявки: {request.code}",
            buttons=get_main_menu_buttons(client),
        )
        return {"status": "ok", "kind": "service_request"}

    if client.max_chat_id in WAITING_DISCOUNT_CONTACT:
        WAITING_DISCOUNT_CONTACT.discard(client.max_chat_id)

        if client.discount_request_used:
            send_max_notification(
                client.max_chat_id,
                "Вы уже использовали возможность оформить скидку.",
                buttons=get_main_menu_buttons(client),
            )
            return {"status": "ok", "kind": "discount_already_used"}

        request = create_service_request(
            db=db,
            request_type="DISCOUNT",
            client=client,
            contact_text=text,
            referrer_client_id=client.referred_by_id,
        )

        client.discount_request_used = True
        db.commit()
        db.refresh(client)

        mark_referral_requested(db, client.id, request.code)

        notify_owner(
            f"Новая заявка на услугу по скидке.\n"
            f"Код заявки: {request.code}\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Данные: {text}\n"
            f"id реферала: {client.referred_by_id}",
            buttons=get_owner_reward_buttons(request.id),
        )

        send_max_notification(
            client.max_chat_id,
            f"Спасибо за обращение. Для получения скидки с вами свяжется наш менеджер.\n"
            f"Код вашей заявки: {request.code}",
            buttons=get_main_menu_buttons(client),
        )
        return {"status": "ok", "kind": "discount_request"}

    if client.max_chat_id in WAITING_BONUS_SPEND:
        WAITING_BONUS_SPEND.discard(client.max_chat_id)

        contact_text, amount = parse_phone_and_amount(text)
        if amount is None:
            send_max_notification(
                client.max_chat_id,
                "Не удалось определить сумму в скобках. Повторите в формате:\nИванов Иван, 79990000000 (500)",
                buttons=get_main_menu_buttons(client),
            )
            return {"status": "ok", "kind": "bonus_spend_bad_amount"}

        current_balance = float(client.balance or 0)
        if amount <= 0:
            send_max_notification(
                client.max_chat_id,
                "Сумма списания должна быть больше нуля.",
                buttons=get_main_menu_buttons(client),
            )
            return {"status": "ok", "kind": "bonus_spend_non_positive"}

        if amount > current_balance:
            send_max_notification(
                client.max_chat_id,
                f"Недостаточно бонусов. Ваш баланс: {current_balance:.2f} руб.",
                buttons=get_main_menu_buttons(client),
            )
            return {"status": "ok", "kind": "bonus_spend_not_enough"}

        client.balance = current_balance - amount
        db.commit()
        db.refresh(client)

        request = create_service_request(
            db=db,
            request_type="BONUS_SPEND",
            client=client,
            contact_text=contact_text,
            bonus_amount=amount,
        )

        notify_owner(
            f"Списание бонуса.\n"
            f"Клиент: {client.name}\n"
            f"user_id: {client.max_chat_id}\n"
            f"Данные: {contact_text}\n"
            f"Списано бонусом: {amount:.2f} руб.\n"
            f"Код заявки: {request.code}"
        )

        send_max_notification(
            client.max_chat_id,
            f"Бонус успешно списан.\n"
            f"Сумма списания: {amount:.2f} руб.\n"
            f"Остаток баланса: {float(client.balance or 0):.2f} руб.",
            buttons=get_main_menu_buttons(client),
        )
        return {"status": "ok", "kind": "bonus_spend_done"}

    reply, buttons = route_action(client, text or "/start")
    send_max_notification(target_id, reply, buttons=buttons)
    return {"status": "ok", "kind": "message"}




















