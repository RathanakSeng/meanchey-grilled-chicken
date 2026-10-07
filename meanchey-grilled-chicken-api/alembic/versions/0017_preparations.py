"""preparations: satay sachets and packaging materials; material prep_role; preparation movements

- `inventory_materials.prep_role` (`none` | `packaging` | `satay_sauce` | `zip_bag_2` |
  `zip_bag_4`, default `packaging`; one material per satay input). Backfill: Marinade sauce →
  none; Satay sauce / Zip bag 7 (2) / Zip bag 7 (4) by their icon key (else English name); every
  other material stays packaging.
- `preparations`, `preparation_lines`, `preparation_counters` (codes PP-YYYYMMDD-NNN per day).
- `inventory_movements.preparation_id` (FK, SET NULL) and source `preparation`;
  notification type `preparation.finished`.

The prepared twins (`<material item_code>_prepared`) and the satay sachet items need no
migration: balance rows are created at startup and on demand.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = (
    "production",
    "adjustment",
    "order",
    "order_return",
    "material_add",
    "material_remove",
    "material_unit_change",
)
NEW_SOURCES = (*OLD_SOURCES, "preparation")
OLD_TYPES = (
    "production.processing_finished",
    "production.completed",
    "order.delivering",
    "order.delivered",
    "order.return_pending",
    "order.returns_reviewed",
)
NEW_TYPES = (*OLD_TYPES, "preparation.finished")
PREP_ROLES = ("none", "packaging", "satay_sauce", "zip_bag_2", "zip_bag_4")
SINGLE_PREP_ROLES = ("satay_sauce", "zip_bag_2", "zip_bag_4")
# role -> (icon_key, English name) of the default material that takes it.
BACKFILL = {
    "satay_sauce": ("satay", "satay sauce"),
    "zip_bag_2": ("zip_bag_2", "zip bag 7 (2-piece packs)"),
    "zip_bag_4": ("zip_bag_4", "zip bag 7 (4-piece packs)"),
}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk(t: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{t}_{column}_users", ondelete="SET NULL"
    )


def _ts(name: str, nullable: bool = True) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    t = "inventory_materials"
    op.add_column(
        t,
        sa.Column("prep_role", sa.String(16), server_default="packaging", nullable=False),
    )
    op.create_check_constraint(f"ck_{t}_prep_role", t, _in("prep_role", PREP_ROLES))
    op.execute(f"UPDATE {t} SET prep_role = 'none' WHERE system_code = 'marinade'")
    for role, (icon_key, name_en) in BACKFILL.items():
        # The best match only (active first, then the oldest): one material per role.
        op.execute(
            f"UPDATE {t} SET prep_role = '{role}' WHERE id = ("
            f"SELECT id FROM {t} WHERE system_code IS NULL AND prep_role = 'packaging' "
            f"AND (icon_key = '{icon_key}' OR lower(name_en) = '{name_en}') "
            "ORDER BY archived_at NULLS FIRST, (icon_key IS NULL), created_at LIMIT 1)"
        )
    op.create_index(
        f"uq_{t}_prep_role",
        t,
        ["prep_role"],
        unique=True,
        postgresql_where=sa.text(_in("prep_role", SINGLE_PREP_ROLES)),
    )

    op.create_table(
        "preparation_counters",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("day", name="pk_preparation_counters"),
    )

    t = "preparations"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("prepared_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("finished_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        _ts("finished_at"),
        _ts("cancelled_at"),
        sa.CheckConstraint(
            _in("type", ("satay_sachet", "packaging_material")), name=f"ck_{t}_type"
        ),
        sa.CheckConstraint(
            _in("status", ("draft", "finished", "cancelled")), name=f"ck_{t}_status"
        ),
        sa.CheckConstraint("char_length(note) <= 1000", name=f"ck_{t}_note_length"),
        sa.CheckConstraint(
            "(status = 'finished') = (prepared_date IS NOT NULL)",
            name=f"ck_{t}_prepared_date_matches",
        ),
        _user_fk(t, "created_by"),
        _user_fk(t, "updated_by"),
        _user_fk(t, "finished_by"),
        _user_fk(t, "cancelled_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("code", name=f"uq_{t}_code"),
    )
    op.create_index(f"ix_{t}_prepared_date", t, ["prepared_date"])

    t = "preparation_lines"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("preparation_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("pack_size", sa.SmallInteger(), nullable=True),
        sa.Column("satay_g", sa.Numeric(14, 1), nullable=True),
        sa.Column("sachets", sa.Integer(), nullable=True),
        sa.Column("material_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(8), nullable=True),
        sa.CheckConstraint(
            "(pack_size IS NOT NULL AND material_id IS NULL) OR "
            "(pack_size IS NULL AND material_id IS NOT NULL AND satay_g IS NULL "
            "AND sachets IS NULL)",
            name=f"ck_{t}_kind",
        ),
        sa.CheckConstraint("pack_size IS NULL OR pack_size IN (2, 4)", name=f"ck_{t}_pack_size"),
        sa.CheckConstraint(
            "(satay_g IS NULL OR satay_g >= 0) AND (quantity IS NULL OR quantity >= 0) "
            "AND (sachets IS NULL OR sachets >= 0)",
            name=f"ck_{t}_nonnegative",
        ),
        sa.CheckConstraint("unit IS NULL OR unit IN ('kg', 'g', 'count')", name=f"ck_{t}_unit"),
        sa.ForeignKeyConstraint(
            ["preparation_id"],
            ["preparations.id"],
            name=f"fk_{t}_preparation_id_preparations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["inventory_materials.id"],
            name=f"fk_{t}_material_id_inventory_materials",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("preparation_id", "pack_size", name=f"uq_{t}_pack_size"),
        sa.UniqueConstraint("preparation_id", "material_id", name=f"uq_{t}_material"),
    )
    op.create_index(f"ix_{t}_preparation_id", t, ["preparation_id"])
    op.create_index(f"ix_{t}_material_id", t, ["material_id"])

    t = "inventory_movements"
    op.add_column(t, sa.Column("preparation_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        f"fk_{t}_preparation_id_preparations",
        t,
        "preparations",
        ["preparation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(f"ix_{t}_preparation_id", t, ["preparation_id"])
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(f"ck_{t}_source", t, _in("source", NEW_SOURCES))

    t = "notifications"
    op.drop_constraint(f"ck_{t}_type", t, type_="check")
    op.create_check_constraint(f"ck_{t}_type", t, _in("type", NEW_TYPES))


def downgrade() -> None:
    # Preparations moved stock: dropping them would leave movements and balances nobody can
    # explain. Refuse instead.
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM preparations"))
    if count:
        raise RuntimeError(f"{count} preparation(s) exist; they can't be downgraded")

    t = "notifications"
    op.execute(f"DELETE FROM {t} WHERE type = 'preparation.finished'")
    op.drop_constraint(f"ck_{t}_type", t, type_="check")
    op.create_check_constraint(f"ck_{t}_type", t, _in("type", OLD_TYPES))

    t = "inventory_movements"
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(f"ck_{t}_source", t, _in("source", OLD_SOURCES))
    op.drop_index(f"ix_{t}_preparation_id", table_name=t)
    op.drop_constraint(f"fk_{t}_preparation_id_preparations", t, type_="foreignkey")
    op.drop_column(t, "preparation_id")
    # The prepared items' balance rows (empty without preparations).
    op.execute(
        "DELETE FROM inventory_balances WHERE item_code LIKE '%\\_prepared' "
        "OR item_code IN ('satay_sachet_2', 'satay_sachet_4')"
    )

    op.drop_table("preparation_lines")
    op.drop_table("preparations")
    op.drop_table("preparation_counters")

    t = "inventory_materials"
    op.drop_index(f"uq_{t}_prep_role", table_name=t)
    op.drop_constraint(f"ck_{t}_prep_role", t, type_="check")
    op.drop_column(t, "prep_role")
