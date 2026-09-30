"""packaging plans between steps 2 and 3, notifications, Telegram link tokens

- `production_plans`: one row per batch, created when step 2 is finished. In-progress batches
  whose step 2 is already finished get a `pending` plan here (step 3 waits for it). Completed and
  cancelled batches get none (shown as "no plan, before plans existed").
- `notifications`: one row per recipient (the bell), with the Telegram delivery status.
- `telegram_link_tokens`: one-time tokens for the superadmin's "Link Telegram" deep link.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _user_fk(table: str, column: str, ondelete: str = "SET NULL") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{table}_{column}_users", ondelete=ondelete
    )


def upgrade() -> None:
    t = "production_plans"
    op.create_table(
        t,
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("expected_big", sa.Integer(), nullable=True),
        sa.Column("expected_small", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('pending', 'confirmed')", name=f"ck_{t}_status"),
        sa.CheckConstraint(
            "expected_big >= 0 AND expected_small >= 0", name=f"ck_{t}_nonnegative"
        ),
        sa.CheckConstraint(
            "status <> 'confirmed' OR (expected_big IS NOT NULL AND expected_small IS NOT NULL)",
            name=f"ck_{t}_confirmed_complete",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["production_batches.id"],
            name=f"fk_{t}_batch_id_production_batches",
            ondelete="CASCADE",
        ),
        _user_fk(t, "confirmed_by"),
        _user_fk(t, "updated_by"),
        sa.PrimaryKeyConstraint("batch_id", name=f"pk_{t}"),
    )
    op.create_index("ix_production_plans_status", t, ["status"])
    # Batches waiting at step 3 today: their plan starts pending, so step 3 waits for it.
    op.execute(
        "INSERT INTO production_plans (batch_id, status) "
        "SELECT o.batch_id, 'pending' FROM production_outputs o "
        "JOIN production_batches b ON b.id = o.batch_id "
        "WHERE o.status = 'finished' AND b.status = 'in_progress'"
    )

    t = "notifications"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "telegram_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("telegram_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('production.processing_finished', 'production.completed')",
            name=f"ck_{t}_type",
        ),
        sa.CheckConstraint(
            "telegram_status IN ('pending', 'sent', 'failed', 'not_linked', 'bot_off')",
            name=f"ck_{t}_telegram_status",
        ),
        _user_fk(t, "user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
    )
    op.create_index(
        "ix_notifications_user_read_created", t, ["user_id", "read_at", "created_at"]
    )

    t = "telegram_link_tokens"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _user_fk(t, "user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("token_hash", name=f"uq_{t}_token_hash"),
    )
    op.create_index("ix_telegram_link_tokens_user_id", t, ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_link_tokens_user_id", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_production_plans_status", table_name="production_plans")
    op.drop_table("production_plans")
