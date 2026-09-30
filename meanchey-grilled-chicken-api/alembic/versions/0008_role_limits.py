"""configurable role limits; several general managers allowed

- `role_limits`: max active users per role, seeded general_manager 2, supervisor 3, staff 10
  (null = unlimited, not for the general manager). Existing users are left as they are, even when a
  role is already above its seeded limit: it is simply full until some leave it.
- `uq_users_single_active_gm` is dropped: the general manager count is now the limit's job.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    t = "role_limits"
    op.create_table(
        t,
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("max_active", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('general_manager', 'supervisor', 'staff')", name=f"ck_{t}_role"),
        sa.CheckConstraint(
            "max_active IS NULL OR max_active BETWEEN 1 AND 999", name=f"ck_{t}_max_active"
        ),
        sa.CheckConstraint(
            "role <> 'general_manager' OR max_active IS NOT NULL", name=f"ck_{t}_gm_limited"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=f"fk_{t}_updated_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("role", name=f"pk_{t}"),
    )
    op.execute(
        "INSERT INTO role_limits (role, max_active) VALUES "
        "('general_manager', 2), ('supervisor', 3), ('staff', 10)"
    )
    op.drop_index("uq_users_single_active_gm", table_name="users")


def downgrade() -> None:
    # Fails if several general managers are active: deactivate the extra ones first.
    op.create_index(
        "uq_users_single_active_gm",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'general_manager' AND is_active"),
    )
    op.drop_table("role_limits")
