"""widen chat message content for mysql

Revision ID: 20260824_0006
Revises: 20260818_0005
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0006"
down_revision: str | Sequence[str] | None = "20260818_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(sa.text("ALTER TABLE chat_messages MODIFY content MEDIUMTEXT NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(sa.text("ALTER TABLE chat_messages MODIFY content TEXT NOT NULL"))
