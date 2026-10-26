"""Таблиці MVP (ТЗ розд. 4). Час – завжди UTC, timestamptz."""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, Table, Text, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_link_code_hash: Mapped[str | None] = mapped_column(Text)
    tg_link_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pwd_reset_hash: Mapped[str | None] = mapped_column(Text)  # SHA-256 одноразового токена зі скидання пароля
    pwd_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_min_severity: Mapped[str] = mapped_column(Text, default="warning", server_default="warning")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status in ('active','blocked')"),
                      CheckConstraint("notify_min_severity in ('warning','critical')"))


class Target(Base):
    __tablename__ = "targets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    check_type: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="manual", server_default="manual")
    # SET NULL: видалення сервера не знищує пов'язані сервіси та їхню історію
    host_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("targets.id", ondelete="SET NULL"))
    external_id: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    expected_status: Mapped[str] = mapped_column(Text, default="200-399", server_default="200-399")
    interval_s: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    agent_token_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    agent_version: Mapped[str | None] = mapped_column(Text)
    clock_offset_s: Mapped[float | None] = mapped_column(Float)
    agent_interval_s: Mapped[int | None] = mapped_column(Integer)  # інтервал із agent.toml: він незалежний від interval_s
    status: Mapped[str] = mapped_column(Text, default="unknown", server_default="unknown")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))  # прихований виявлений об'єкт
    ping_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))  # лише сервери з публічною адресою
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def effective_interval_s(self) -> int:
        """Як часто реально приходять дані: більший з інтервалів об'єкта й агента."""
        return max(self.interval_s, self.agent_interval_s or 0)

    __table_args__ = (
        CheckConstraint("type in ('server','service','container','database')"),
        CheckConstraint("status in ('ok','warning','critical','unavailable','unknown')"),
        CheckConstraint("interval_s >= 15"),
        Index("uq_targets_host_external", "host_id", "external_id", unique=True,
              postgresql_where=text("external_id is not null")),
    )


# Гіпертаблиця TimescaleDB без власного id: ORM-клас не потрібен, лише Core (ТЗ 4.1).
metrics = Table(
    "metrics", Base.metadata,
    Column("target_id", BigInteger, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("instance", Text, nullable=False, server_default=""),
    Column("value", Float, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Index("ix_metrics_series", "target_id", "name", "instance", text("ts DESC")),
)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    target_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("targets.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(Text)
    instance: Mapped[str] = mapped_column(Text, default="", server_default="")
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open", server_default="open")
    suppressed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("incidents.id"))
    value_at_open: Mapped[float | None] = mapped_column(Float)
    first_breach_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolve_comment: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("severity in ('warning','critical')"),
        CheckConstraint("status in ('open','acknowledged','resolved','suppressed')"),
        # не більше одного незакритого інциденту на ряд
        Index("one_open_incident", "target_id", "metric", "instance", unique=True,
              postgresql_where=text("status <> 'resolved'")),
        Index("ix_incidents_owner", "owner_id", "status", text("started_at DESC")),
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    incident_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint(
        "type in ('detected','opened','escalated','deescalated','acknowledged','resolved','suppressed','notified')"),)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    cause: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    applies_to: Mapped[list[str]] = mapped_column(ARRAY(Text))
    conditions: Mapped[list] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    incident_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("incidents.id", ondelete="CASCADE"), unique=True)
    rule_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("rules.id", ondelete="SET NULL"))
    matched_ratio: Mapped[float] = mapped_column(Float, default=0)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    alternatives: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThresholdRow(Base):
    """Власний поріг користувача: для одного об'єкта або (target_id = NULL) для всіх його об'єктів."""
    __tablename__ = "thresholds"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    target_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("targets.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(Text)
    warn_value: Mapped[float | None] = mapped_column(Float)
    crit_value: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("uq_thresholds_scope", "owner_id", "target_id", "metric", unique=True, postgresql_nulls_not_distinct=True),
                      CheckConstraint("duration_s >= 0 AND duration_s <= 3600"))


class RuleOverride(Base):
    """Базове правило, вимкнене (або знову увімкнене) окремим користувачем."""
    __tablename__ = "rule_overrides"
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("kind in ('opened','escalated','resolved','test')"),
                      CheckConstraint("status in ('pending','sent','failed')"),
                      Index("ix_notifications_pending", "next_attempt_at", postgresql_where=text("status = 'pending'")))
