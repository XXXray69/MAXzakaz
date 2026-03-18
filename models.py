from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

import config

Base = declarative_base()

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    max_chat_id = Column(String(128), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, default="Unknown")
    referral_code = Column(String(64), unique=True, nullable=False, index=True)

    referred_by_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    referral_locked = Column(Boolean, nullable=False, default=False)  # уже закреплён за первым реферером
    discount_request_used = Column(Boolean, nullable=False, default=False)  # уже нажимал "Хочу скидку"
    balance = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    referred_by = relationship("Client", remote_side=[id])

    invited_events = relationship(
        "ReferralEvent",
        foreign_keys="ReferralEvent.inviter_client_id",
        back_populates="inviter_client",
    )

    referred_events = relationship(
        "ReferralEvent",
        foreign_keys="ReferralEvent.referred_client_id",
        back_populates="referred_client",
    )

    requests = relationship("ServiceRequest", back_populates="client")


class ReferralEvent(Base):
    __tablename__ = "referral_events"

    id = Column(Integer, primary_key=True)

    inviter_client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    referred_client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    status = Column(String(32), nullable=False, default="VISITED")
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    inviter_client = relationship(
        "Client",
        foreign_keys=[inviter_client_id],
        back_populates="invited_events",
    )
    referred_client = relationship(
        "Client",
        foreign_keys=[referred_client_id],
        back_populates="referred_events",
    )


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True)

    code = Column(String(32), unique=True, nullable=False, index=True)
    request_type = Column(String(32), nullable=False)  # DISCOUNT / BONUS_SPEND

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    referrer_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)

    account_name = Column(String(255), nullable=False, default="Unknown")
    client_max_chat_id = Column(String(128), nullable=False)

    contact_text = Column(Text, nullable=False)  # ФИО + телефон
    bonus_amount = Column(Float, nullable=True)  # сумма награждения или списания

    status = Column(String(32), nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    client = relationship("Client", foreign_keys=[client_id], back_populates="requests")


def initialize_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()




