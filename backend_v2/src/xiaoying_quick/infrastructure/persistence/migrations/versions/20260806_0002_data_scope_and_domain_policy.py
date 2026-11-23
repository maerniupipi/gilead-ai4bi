"""add identity data scope and domain SQL policy

Revision ID: 20260806_0002
Revises: 20260806_0001
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0002"
down_revision: str | Sequence[str] | None = "20260806_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_user_data_scopes",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("organizations", sa.JSON(), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["identity_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    # Secure compatibility default: pre-existing bindings authorize no object
    # until an administrator explicitly rebinds the domain policy.
    # MySQL rejects a literal default for JSON columns, so it receives the
    # expression form ('[]') while SQLite keeps the plain literal.
    bind = op.get_bind()
    json_default = (
        sa.text("('[]')") if bind.dialect.name in {"mysql", "mariadb"} else sa.text("'[]'")
    )
    with op.batch_alter_table("domain_bindings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "allowed_objects",
                sa.JSON(),
                server_default=json_default,
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "allowed_schemas",
                sa.JSON(),
                server_default=json_default,
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "allowed_join_keys",
                sa.JSON(),
                server_default=json_default,
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("domain_bindings", schema=None) as batch_op:
        batch_op.drop_column("allowed_join_keys")
        batch_op.drop_column("allowed_schemas")
        batch_op.drop_column("allowed_objects")
    op.drop_table("identity_user_data_scopes")
