"""persist labs attached to a data source with name + token

Revision ID: 20260831_0008
Revises: 20260826_0007
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0008"
down_revision: str | Sequence[str] | None = "20260826_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_labs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("data_source_id", sa.String(length=64), nullable=False),
        sa.Column("lab_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("token_secret_ref", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lab_id", name="uq_source_labs_lab_id"),
    )
    op.create_index("ix_source_labs_data_source_id", "source_labs", ["data_source_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_source_labs_data_source_id", table_name="source_labs")
    op.drop_table("source_labs")
