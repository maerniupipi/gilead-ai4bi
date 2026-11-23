"""usage_events.question for user/parent question display

Revision ID: 20261025_0014
Revises: 20261025_0013
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0014"
down_revision: str | Sequence[str] | None = "20261025_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("question", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "question")
