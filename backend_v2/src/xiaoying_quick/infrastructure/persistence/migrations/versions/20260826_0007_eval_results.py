"""persist eval batch results one item at a time

Revision ID: 20260826_0007
Revises: 20260824_0006
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0007"
down_revision: str | Sequence[str] | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_user_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eval_batches_owner_created",
        "eval_batches",
        ["owner_user_id", "created_at"],
        unique=False,
    )
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        from sqlalchemy.dialects.mysql import MEDIUMTEXT

        long_text = MEDIUMTEXT()
    else:
        long_text = sa.Text()
    op.create_table(
        "eval_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=False),
        sa.Column("sheet", sa.String(length=128), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("clarify", long_text, nullable=False),
        sa.Column("sql_text", long_text, nullable=False),
        sa.Column("labs", long_text, nullable=False),
        sa.Column("answer", long_text, nullable=False),
        sa.Column("duration", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("answer_preview", sa.String(length=160), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("extra_values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["eval_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "sheet", "row_number", name="uq_eval_results_batch_sheet_row"),
    )
    op.create_index(
        "ix_eval_results_batch",
        "eval_results",
        ["batch_id", "sheet", "row_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_eval_results_batch", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_batches_owner_created", table_name="eval_batches")
    op.drop_table("eval_batches")
