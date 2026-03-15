from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
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

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    referred_by = relationship("Client", remote_side=[id])

    referrals_sent = relationship(
        "ReferralEvent",
        foreign_keys="ReferralEvent.inviter_client_id",
        back_populates="inviter_client",
    )

    referrals_received = relationship(
        "ReferralEvent",
        foreign_keys="ReferralEvent.referred_client_id",
        back_populates="referred_client",
    )


class ReferralEvent(Base):
    __tablename__ = "referral_events"

    id = Column(Integer, primary_key=True)
    inviter_client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    referred_client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)

    status = Column(String(32), nullable=False, default="PENDING")
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    inviter_client = relationship(
        "Client",
        foreign_keys=[inviter_client_id],
        back_populates="referrals_sent",
    )

    referred_client = relationship(
        "Client",
        foreign_keys=[referred_client_id],
        back_populates="referrals_received",
    )


def initialize_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()




