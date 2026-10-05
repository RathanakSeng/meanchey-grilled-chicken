"""inventory materials: inventory_materials; grams on balances and movements; material sources

- `inventory_materials`: items that don't come from production (string, skewers, sauces...),
  names unique among active ones per language (partial unique indexes on lower(name)).
- `inventory_balances.g`, `inventory_movements.g_delta` / `balance_g_after` (NUMERIC(14,1)):
  materials measured in grams. `has_delta` now accepts a grams-only movement.
- `inventory_movements.source` widened to 24 characters, with `material_add`,
  `material_remove` and `material_unit_change`.

The default materials (and Marinade sauce, `system_code = marinade`) are seeded at startup
(services/material_service.ensure_defaults), not here; the new permissions are registered and
backfilled at startup too.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = ("production", "adjustment", "order", "order_return")
NEW_SOURCES = (*OLD_SOURCES, "material_add", "material_remove", "material_unit_change")
G = sa.Numeric(14, 1)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _user_fk(t: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{t}_{column}_users", ondelete="SET NULL"
    )


def upgrade() -> None:
    t = "inventory_materials"
    op.create_table(
        t,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_code", sa.String(64), nullable=False),
        sa.Column("name_km", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False),
        sa.Column("system_code", sa.String(32), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(_in("unit", ("kg", "g", "count")), name=f"ck_{t}_unit"),
        sa.CheckConstraint(
            "char_length(name_km) BETWEEN 1 AND 100 AND char_length(name_en) BETWEEN 1 AND 100",
            name=f"ck_{t}_names",
        ),
        _user_fk(t, "archived_by"),
        _user_fk(t, "created_by"),
        _user_fk(t, "updated_by"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{t}"),
        sa.UniqueConstraint("item_code", name=f"uq_{t}_item_code"),
        sa.UniqueConstraint("system_code", name=f"uq_{t}_system_code"),
    )
    for lang in ("km", "en"):
        op.create_index(
            f"uq_{t}_active_name_{lang}",
            t,
            [sa.text(f"lower(name_{lang})")],
            unique=True,
            postgresql_where=sa.text("archived_at IS NULL"),
        )

    t = "inventory_balances"
    op.add_column(t, sa.Column("g", G, nullable=True))
    op.create_check_constraint(f"ck_{t}_g", t, "g >= 0")

    t = "inventory_movements"
    op.add_column(t, sa.Column("g_delta", G, nullable=True))
    op.add_column(t, sa.Column("balance_g_after", G, nullable=True))
    op.alter_column(t, "source", type_=sa.String(24), existing_type=sa.String(16))
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(f"ck_{t}_source", t, _in("source", NEW_SOURCES))
    op.drop_constraint(f"ck_{t}_has_delta", t, type_="check")
    op.create_check_constraint(
        f"ck_{t}_has_delta",
        t,
        "count_delta IS NOT NULL OR kg_delta IS NOT NULL OR g_delta IS NOT NULL",
    )


def downgrade() -> None:
    t = "inventory_movements"
    op.execute(
        "DELETE FROM inventory_movements WHERE source IN "
        "('material_add', 'material_remove', 'material_unit_change') OR item_code LIKE 'material\\_%'"
    )
    op.drop_constraint(f"ck_{t}_has_delta", t, type_="check")
    op.create_check_constraint(
        f"ck_{t}_has_delta", t, "count_delta IS NOT NULL OR kg_delta IS NOT NULL"
    )
    op.drop_constraint(f"ck_{t}_source", t, type_="check")
    op.create_check_constraint(f"ck_{t}_source", t, _in("source", OLD_SOURCES))
    op.alter_column(t, "source", type_=sa.String(16), existing_type=sa.String(24))
    op.drop_column(t, "balance_g_after")
    op.drop_column(t, "g_delta")

    t = "inventory_balances"
    op.execute("DELETE FROM inventory_balances WHERE item_code LIKE 'material\\_%'")
    op.drop_constraint(f"ck_{t}_g", t, type_="check")
    op.drop_column(t, "g")

    op.execute("DELETE FROM app_settings WHERE key = 'inventory_materials_seeded'")
    op.drop_table("inventory_materials")
