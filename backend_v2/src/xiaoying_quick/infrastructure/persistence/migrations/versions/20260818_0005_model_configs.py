"""persist selectable chat model configurations

Revision ID: 20260818_0005
Revises: 20260806_0004
Create Date: 2026-08-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0005"
down_revision: str | Sequence[str] | None = "20260806_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("secret_ref", sa.String(length=128), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.2"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="16384"),
        sa.Column("reasoning", sa.String(length=8), nullable=False, server_default="auto"),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="180.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_model_configs_active",
        "model_configs",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_configs_active", table_name="model_configs")
    op.drop_table("model_configs")
