"""Durable per-call capacity reservations and auditable monthly resets."""

from alembic import op
import sqlalchemy as sa

revision = "20261121_0016"
down_revision = "20261025_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "quota_holds",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
    )
    op.create_index("ix_quota_holds_user_id", "quota_holds", ["user_id"])
    op.create_table(
        "quota_resets",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("period", sa.String(7), primary_key=True),
        sa.Column("baseline", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("quota_resets")
    op.drop_table("quota_holds")
