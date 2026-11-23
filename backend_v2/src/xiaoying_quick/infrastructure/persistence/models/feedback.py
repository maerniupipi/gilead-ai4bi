"""Per-run answer feedback (thumbs up / thumbs down)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from xiaoying_quick.infrastructure.persistence.base import Base, utc_now


class AnswerFeedbackModel(Base):
    __tablename__ = "answer_feedback"
    __table_args__ = (
        UniqueConstraint("run_id", "user_id", name="uq_answer_feedback_run_user"),
        Index("ix_answer_feedback_created", "created_at"),
        Index("ix_answer_feedback_rating_created", "rating", "created_at"),
        Index("ix_answer_feedback_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
