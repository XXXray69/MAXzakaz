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
    loyalty_level = Column(String(32), nullable=False, default="BRONZE")
    total_spent_last_period = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    referred_by = relationship("Client", remote_side=[id])
    policies = relationship("Policy", back_populates="client", cascade="all, delete-orphan")
    bonuses = relationship("BonusLedger", back_populates="client", cascade="all, delete-orphan")


class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    policy_type = Column(String(64), nullable=False, index=True)
    premium_amount = Column(Float, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    referral_source_client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    bonus_rate = Column(Float, nullable=False, default=0.0)
    bonus_amount = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    client = relationship("Client", foreign_keys=[client_id], back_populates="policies")


class BonusLedger(Base):
    __tablename__ = "bonus_ledger"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    entry_type = Column(String(64), nullable=False)
    description = Column(Text, nullable=False)
    available_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), nullable=True)
    referral_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    client = relationship("Client", back_populates="bonuses")


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    status = Column(String(32), nullable=False, default="PENDING")
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)


class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    only_with_referrals = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def initialize_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
