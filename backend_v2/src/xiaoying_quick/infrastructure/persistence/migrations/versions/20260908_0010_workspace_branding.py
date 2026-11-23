"""persist workspace branding for white-label deployments

Revision ID: 20260908_0010
Revises: 20260901_0009
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0010"
down_revision: str | Sequence[str] | None = "20260901_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_branding",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("character_name", sa.String(length=32), nullable=False),
        sa.Column("company_intro", sa.String(length=64), nullable=False),
        sa.Column("theme_id", sa.String(length=32), nullable=False),
        sa.Column("logo_kind", sa.String(length=16), nullable=False),
        sa.Column("logo_preset_id", sa.String(length=32), nullable=False),
        sa.Column("logo_asset_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_branding")
