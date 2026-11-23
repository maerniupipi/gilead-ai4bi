"""usage_events token consumption ledger

Revision ID: 20261025_0013
Revises: 20261023_0012
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0013"
down_revision: str | Sequence[str] | None = "20261023_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=96), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_created", "usage_events", ["created_at"])
    op.create_index(
        "ix_usage_events_user_created", "usage_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_usage_events_purpose_created", "usage_events", ["purpose", "created_at"]
    )
    op.create_index(
        "ix_usage_events_run_created", "usage_events", ["run_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_run_created", table_name="usage_events")
    op.drop_index("ix_usage_events_purpose_created", table_name="usage_events")
    op.drop_index("ix_usage_events_user_created", table_name="usage_events")
    op.drop_index("ix_usage_events_created", table_name="usage_events")
    op.drop_table("usage_events")
