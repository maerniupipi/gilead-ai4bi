from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class AgentConfigModel(TimestampMixin, Base):
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tool_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    agent_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    extras: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
