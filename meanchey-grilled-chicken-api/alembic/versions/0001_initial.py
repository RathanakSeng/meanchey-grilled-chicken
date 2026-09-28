"""initial schema: users, permissions, tokens, audit logs, bot prefs

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = postgresql.ENUM(
    "superadmin", "general_manager", "supervisor", "staff", name="user_role", create_type=False
)


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("position", sa.String(length=32), nullable=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("language", sa.String(length=8), server_default="km", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(role = 'staff') = (position IS NOT NULL)", name="ck_users_position_staff_only"
        ),
        sa.CheckConstraint(
            "role = 'superadmin' OR telegram_username IS NOT NULL",
            name="ck_users_telegram_username_required",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_users_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(
        "uq_users_single_superadmin",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'superadmin'"),
    )
    op.create_index(
        "uq_users_single_active_gm",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'general_manager' AND is_active"),
    )
    op.create_index(
        "uq_users_active_telegram_username",
        "users",
        ["telegram_username"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_users_active_telegram_user_id",
        "users",
        ["telegram_user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_km", sa.String(length=120), nullable=False),
        sa.Column("description_en", sa.Text(), nullable=False),
        sa.Column("description_km", sa.Text(), nullable=False),
        sa.Column("assignable_to", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_permissions"),
    )
    op.create_index("ix_permissions_module", "permissions", ["module"])

    op.create_table(
        "user_permissions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_permissions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["permissions.code"],
            name="fk_user_permissions_permission_code_permissions",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_user_permissions_granted_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "permission_code", name="pk_user_permissions"),
    )
    op.create_index("ix_user_permissions_granted_by", "user_permissions", ["granted_by"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_logs_actor_id_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_audit_logs_target_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_target_user_id", "audit_logs", ["target_user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "bot_prefs",
        sa.Column("telegram_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("telegram_user_id", name="pk_bot_prefs"),
    )


def downgrade() -> None:
    op.drop_table("bot_prefs")
    op.drop_table("audit_logs")
    op.drop_table("refresh_tokens")
    op.drop_table("user_permissions")
    op.drop_table("permissions")
    op.drop_table("users")
    user_role.drop(op.get_bind(), checkfirst=True)
