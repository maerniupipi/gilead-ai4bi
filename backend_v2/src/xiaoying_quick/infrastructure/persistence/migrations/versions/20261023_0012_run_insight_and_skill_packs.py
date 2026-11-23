"""run mode/parent/insight_meta + skill_packs

Revision ID: 20261023_0012
Revises: 20261020_0011
Create Date: 2026-10-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0012"
down_revision: str | Sequence[str] | None = "20261020_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="normal")
        )
        batch.add_column(sa.Column("parent_run_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("insight_meta", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_runs_parent_run_id",
            "runs",
            ["parent_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_runs_parent_created", ["parent_run_id", "created_at"])

    op.create_table(
        "skill_packs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("blurb", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_skill_packs_type_status", "type", "status"),
    )


def downgrade() -> None:
    op.drop_table("skill_packs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_parent_created")
        batch.drop_constraint("fk_runs_parent_run_id", type_="foreignkey")
        batch.drop_column("insight_meta")
        batch.drop_column("parent_run_id")
        batch.drop_column("mode")
