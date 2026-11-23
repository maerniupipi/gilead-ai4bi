from __future__ import annotations

from sqlalchemy import Boolean, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class ModelConfigModel(TimestampMixin, Base):
    __tablename__ = "model_configs"
    __table_args__ = (Index("ix_model_configs_active", "is_active"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=16_384)
    reasoning: Mapped[str] = mapped_column(String(8), nullable=False, default="auto")
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=180.0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
