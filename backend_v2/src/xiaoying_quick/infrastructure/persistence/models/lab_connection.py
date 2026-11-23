"""Workspace laboratory selection; credentials are stored as secret references."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class LabConnectionModel(TimestampMixin, Base):
    __tablename__ = "lab_connection"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    active_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    mock_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profiles: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
