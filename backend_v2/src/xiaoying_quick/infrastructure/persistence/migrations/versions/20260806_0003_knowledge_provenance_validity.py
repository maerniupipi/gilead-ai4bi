"""add governed knowledge provenance and validity

Revision ID: 20260806_0003
Revises: 20260806_0002
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0003"
down_revision: str | Sequence[str] | None = "20260806_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_candidates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_question", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("clarification_question", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("clarification_answer", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("applicability", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_knowledge_candidates_validity",
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
        )

    with op.batch_alter_table("knowledge_entries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("applicability", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_knowledge_entries_validity",
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_entries", schema=None) as batch_op:
        batch_op.drop_constraint("ck_knowledge_entries_validity", type_="check")
        batch_op.drop_column("valid_until")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("applicability")

    with op.batch_alter_table("knowledge_candidates", schema=None) as batch_op:
        batch_op.drop_constraint("ck_knowledge_candidates_validity", type_="check")
        batch_op.drop_column("valid_until")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("applicability")
        batch_op.drop_column("clarification_answer")
        batch_op.drop_column("clarification_question")
        batch_op.drop_column("source_question")
