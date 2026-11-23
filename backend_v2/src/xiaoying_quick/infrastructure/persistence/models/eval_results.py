"""Eval batch and per-item result tables."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin

LongText = Text().with_variant(MEDIUMTEXT(), "mysql")


class EvalBatchModel(TimestampMixin, Base):
    __tablename__ = "eval_batches"
    __table_args__ = (Index("ix_eval_batches_owner_created", "owner_user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(200), nullable=False)


class EvalResultModel(TimestampMixin, Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("batch_id", "sheet", "row_number", name="uq_eval_results_batch_sheet_row"),
        Index("ix_eval_results_batch", "batch_id", "sheet", "row_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("eval_batches.id", ondelete="CASCADE"), nullable=False
    )
    sheet: Mapped[str] = mapped_column(String(128), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    clarify: Mapped[str] = mapped_column(LongText, nullable=False, default="")
    sql_text: Mapped[str] = mapped_column("sql_text", LongText, nullable=False, default="")
    labs: Mapped[str] = mapped_column(LongText, nullable=False, default="")
    answer: Mapped[str] = mapped_column(LongText, nullable=False, default="")
    duration: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_preview: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    headers: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    extra_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
