"""Run-owned SQLAlchemy tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from xiaoying_quick.infrastructure.persistence.base import Base, TimestampMixin, utc_now


class RunModel(TimestampMixin, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "idempotency_key", name="uq_runs_owner_idempotency"),
        Index("ix_runs_owner_created", "owner_user_id", "created_at"),
        Index("ix_runs_parent_created", "parent_run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    parent_run_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="RESTRICT"), nullable=True
    )
    insight_meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    next_event_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RunEventModel(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint(column("cursor") > 0, name="ck_run_events_positive_cursor"),
        Index("ix_run_events_created", "created_at"),
    )

    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="RESTRICT"), primary_key=True
    )
    cursor: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
