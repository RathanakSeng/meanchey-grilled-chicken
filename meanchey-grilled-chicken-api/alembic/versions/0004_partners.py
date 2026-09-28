"""suppliers + customers, audit log entity reference, permissions.grantable_by

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTNER_TABLES = ("suppliers", "customers")


def _create_partner_table(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=f"fk_{table}_created_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=f"fk_{table}_updated_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
    )
    op.create_index(f"ix_{table}_name_lower", table, [sa.text("lower(name)")])
    op.create_index(
        f"uq_{table}_active_phone",
        table,
        ["phone"],
        unique=True,
        postgresql_where=sa.text("is_active AND phone IS NOT NULL"),
    )


def upgrade() -> None:
    for table in PARTNER_TABLES:
        _create_partner_table(table)

    op.add_column("audit_logs", sa.Column("entity_type", sa.String(length=32), nullable=True))
    op.add_column("audit_logs", sa.Column("entity_id", sa.Uuid(), nullable=True))
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    op.add_column(
        "permissions",
        sa.Column("grantable_by", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("permissions", "grantable_by")

    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_column("audit_logs", "entity_id")
    op.drop_column("audit_logs", "entity_type")

    for table in reversed(PARTNER_TABLES):
        op.drop_index(f"uq_{table}_active_phone", table_name=table)
        op.drop_index(f"ix_{table}_name_lower", table_name=table)
        op.drop_table(table)
