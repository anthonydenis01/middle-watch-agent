from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Watchlist(Base):
    __tablename__ = 'watchlist'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(10))
    containers: Mapped[list['Container']] = relationship(cascade='all, delete-orphan', passive_deletes=True)


class Container(Base):
    __tablename__ = 'container'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    watchlist_id: Mapped[str] = mapped_column(ForeignKey('watchlist.id', ondelete='CASCADE'), index=True)
    number: Mapped[str] = mapped_column(String(40))
    valid: Mapped[bool] = mapped_column(Boolean)
    invalid_reason: Mapped[str | None] = mapped_column(String(250))
    carrier_label: Mapped[str] = mapped_column(String(20), default='Simulated')
    status: Mapped[str] = mapped_column(String(40), default='INVALID')
    eta: Mapped[str | None] = mapped_column(String(30))
    next_milestone: Mapped[str | None] = mapped_column(String(100))
    journey: Mapped[dict] = mapped_column(JSON, default=dict)
    events: Mapped[list['Event']] = relationship(cascade='all, delete-orphan', passive_deletes=True)
    exceptions: Mapped[list['ExceptionRecord']] = relationship(cascade='all, delete-orphan', passive_deletes=True)


class Event(Base):
    __tablename__ = 'event'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    container_id: Mapped[str] = mapped_column(ForeignKey('container.id', ondelete='CASCADE'), index=True)
    ts: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(40))
    location_unlocode: Mapped[str] = mapped_column(String(5))
    vessel: Mapped[str] = mapped_column(String(100))
    voyage: Mapped[str] = mapped_column(String(30))
    raw: Mapped[dict] = mapped_column(JSON)


class ExceptionRecord(Base):
    __tablename__ = 'exception'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    container_id: Mapped[str] = mapped_column(ForeignKey('container.id', ondelete='CASCADE'), index=True)
    family: Mapped[str] = mapped_column(String(30))
    severity: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    evidence_json: Mapped[list] = mapped_column(JSON)
    rule_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
