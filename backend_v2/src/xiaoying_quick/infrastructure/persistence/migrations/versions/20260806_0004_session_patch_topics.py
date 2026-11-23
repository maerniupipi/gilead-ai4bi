"""isolate session patches by explicit conversation topic

Revision ID: 20260806_0004
Revises: 20260806_0003
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0004"
down_revision: str | Sequence[str] | None = "20260806_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clarification_cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("topic_id", sa.String(length=64), nullable=True))

    with op.batch_alter_table("session_domain_patches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("topic_id", sa.String(length=64), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE clarification_cases "
            "SET topic_id = frame_id WHERE topic_id IS NULL OR topic_id = ''"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE session_domain_patches "
            "SET topic_id = frame_id WHERE topic_id IS NULL OR topic_id = ''"
        )
    )
    # A legacy race could have left more than one active row.  Preserve every
    # historical row, but deterministically keep only the newest effective
    # patch before installing the database-level single-active invariant.
    connection.execute(
        sa.text(
            "UPDATE session_domain_patches SET active = FALSE WHERE id IN ("
            "SELECT id FROM ("
            "SELECT id, ROW_NUMBER() OVER ("
            "PARTITION BY session_id, topic_id "
            "ORDER BY created_at DESC, id DESC"
            ") AS topic_rank FROM session_domain_patches WHERE active = TRUE"
            ") AS ranked WHERE topic_rank > 1"
            ")"
        )
    )

    with op.batch_alter_table("clarification_cases", schema=None) as batch_op:
        batch_op.alter_column(
            "topic_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    with op.batch_alter_table("session_domain_patches", schema=None) as batch_op:
        batch_op.alter_column(
            "topic_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_index(
            "ix_session_patch_topic_active",
            ["session_id", "topic_id", "active"],
            unique=False,
        )

    op.create_index(
        "uq_session_patch_one_active_topic",
        "session_domain_patches",
        ["session_id", "topic_id"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_session_patch_one_active_topic",
        table_name="session_domain_patches",
    )
    with op.batch_alter_table("session_domain_patches", schema=None) as batch_op:
        batch_op.drop_index("ix_session_patch_topic_active")
        batch_op.drop_column("topic_id")

    with op.batch_alter_table("clarification_cases", schema=None) as batch_op:
        batch_op.drop_column("topic_id")
