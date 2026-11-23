from __future__ import annotations

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin


class WorkspaceBrandingModel(TimestampMixin, Base):
    __tablename__ = "workspace_branding"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    character_name: Mapped[str] = mapped_column(String(32), nullable=False)
    company_intro: Mapped[str] = mapped_column(String(64), nullable=False)
    theme_id: Mapped[str] = mapped_column(String(32), nullable=False)
    logo_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    logo_preset_id: Mapped[str] = mapped_column(String(32), nullable=False)
    logo_asset_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
