"""position becomes a free-text job title (VARCHAR(32) -> VARCHAR(50))

Existing values ("worker", "driver") are kept as plain text.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "position",
        existing_type=sa.String(length=32),
        type_=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Truncate anything longer than the old limit so the downgrade can't fail.
    op.execute("UPDATE users SET position = left(position, 32) WHERE length(position) > 32")
    op.alter_column(
        "users",
        "position",
        existing_type=sa.String(length=50),
        type_=sa.String(length=32),
        existing_nullable=True,
    )
