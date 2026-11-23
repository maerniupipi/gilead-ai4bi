"""persist laboratory provider selection and secret references

Revision ID: 20261020_0011
Revises: 20260908_0010
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0011"
down_revision: str | Sequence[str] | None = "20260908_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lab_connection",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("active_provider", sa.String(length=16), nullable=False),
        sa.Column("mock_enabled", sa.Boolean(), nullable=False),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("lab_connection")
