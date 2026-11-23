"""answer_feedback thumbs up/down ledger

Revision ID: 20261025_0015
Revises: 20261025_0014
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0015"
down_revision: str | Sequence[str] | None = "20261025_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "user_id", name="uq_answer_feedback_run_user"),
    )
    op.create_index("ix_answer_feedback_created", "answer_feedback", ["created_at"])
    op.create_index(
        "ix_answer_feedback_rating_created",
        "answer_feedback",
        ["rating", "created_at"],
    )
    op.create_index(
        "ix_answer_feedback_user_created",
        "answer_feedback",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_user_created", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_rating_created", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_created", table_name="answer_feedback")
    op.drop_table("answer_feedback")
