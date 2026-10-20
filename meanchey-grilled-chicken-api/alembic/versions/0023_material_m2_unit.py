"""material unit m2 (square metres) and two m² sticker materials

- `inventory_balances.m2`, `inventory_movements.m2_delta` / `balance_m2_after` (NUMERIC(14,2));
  `has_delta` accepts an m²-only movement; the material and preparation line unit CHECKs accept
  `m2`.
- Data (idempotent, only when the default materials were seeded): the two kg stickers are renamed
  with a ` · kg` suffix when they still have their seeded names, and the two m² stickers
  (`sticker_4_m2`, `sticker_2_m2`, packaging, balance 0, prepared twin balance 0) are created
  once. Each change writes a `material.update` / `material.create` audit entry (`source: seed`).

Downgrade removes every m² material with its lines, movements and balances, restores the names
and the old CHECKs.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

M2 = sa.Numeric(14, 2)
SEEDED_KEY = "inventory_materials_seeded"
# (old km, old en, new km, new en) of the seeded kg stickers.
RENAMES = (
    (
        "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ)",
        "Sticker (4-piece packs)",
        "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · គ.ក",
        "Sticker (4-piece packs) · kg",
    ),
    (
        "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ)",
        "Sticker (2-piece packs)",
        "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · គ.ក",
        "Sticker (2-piece packs) · kg",
    ),
)
# (icon_key, name_km, name_en) of the new m² stickers.
NEW_MATERIALS = (
    ("sticker_4_m2", "ស្ទីកគ័រ (កញ្ចប់ ៤ ដុំ) · ម៉ែត្រការ៉េ", "Sticker (4-piece packs) · m²"),
    ("sticker_2_m2", "ស្ទីកគ័រ (កញ្ចប់ ២ ដុំ) · ម៉ែត្រការ៉េ", "Sticker (2-piece packs) · m²"),
)


def upgrade() -> None:
    op.add_column("inventory_balances", sa.Column("m2", M2, nullable=True))
    op.create_check_constraint("ck_inventory_balances_m2", "inventory_balances", "m2 >= 0")
    t = "inventory_movements"
    op.add_column(t, sa.Column("m2_delta", M2, nullable=True))
    op.add_column(t, sa.Column("balance_m2_after", M2, nullable=True))
    op.drop_constraint(f"ck_{t}_has_delta", t, type_="check")
    op.create_check_constraint(
        f"ck_{t}_has_delta",
        t,
        "count_delta IS NOT NULL OR kg_delta IS NOT NULL OR g_delta IS NOT NULL "
        "OR m2_delta IS NOT NULL",
    )
    op.drop_constraint("ck_inventory_materials_unit", "inventory_materials", type_="check")
    op.create_check_constraint(
        "ck_inventory_materials_unit",
        "inventory_materials",
        "unit IN ('kg', 'g', 'm2', 'count')",
    )
    op.drop_constraint("ck_preparation_lines_unit", "preparation_lines", type_="check")
    op.create_check_constraint(
        "ck_preparation_lines_unit",
        "preparation_lines",
        "unit IS NULL OR unit IN ('kg', 'g', 'm2', 'count')",
    )

    bind = op.get_bind()
    seeded = bind.scalar(sa.text("SELECT 1 FROM app_settings WHERE key = :k"), {"k": SEEDED_KEY})
    if not seeded:
        return  # A fresh database: the app seeds the defaults (material_service.DEFAULTS).
    for old_km, old_en, new_km, new_en in RENAMES:
        rows = bind.execute(
            sa.text(
                "UPDATE inventory_materials SET name_km = :new_km, name_en = :new_en, "
                "updated_at = now() "
                "WHERE name_km = :old_km AND name_en = :old_en AND unit = 'kg' "
                "RETURNING id, item_code"
            ),
            {"new_km": new_km, "new_en": new_en, "old_km": old_km, "old_en": old_en},
        ).all()
        for material_id, item_code in rows:
            bind.execute(
                sa.text(
                    "INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details) "
                    "VALUES (NULL, 'material.update', 'material', :id, "
                    "jsonb_build_object('item_code', CAST(:code AS text), 'name_en', "
                    "CAST(:new_en AS text), 'name_km', CAST(:new_km AS text), 'changes', "
                    "jsonb_build_object('name_km', jsonb_build_array(CAST(:old_km AS text), "
                    "CAST(:new_km AS text)), 'name_en', jsonb_build_array(CAST(:old_en AS text), "
                    "CAST(:new_en AS text))), 'source', 'seed'))"
                ),
                {
                    "id": material_id,
                    "code": item_code,
                    "old_km": old_km,
                    "old_en": old_en,
                    "new_km": new_km,
                    "new_en": new_en,
                },
            )
    for icon_key, name_km, name_en in NEW_MATERIALS:
        exists = bind.scalar(
            sa.text(
                "SELECT 1 FROM inventory_materials WHERE icon_key = :icon "
                "OR (archived_at IS NULL AND (lower(name_en) = lower(:en) "
                "OR lower(name_km) = lower(:km)))"
            ),
            {"icon": icon_key, "en": name_en, "km": name_km},
        )
        if exists:
            continue
        row = bind.execute(
            sa.text(
                "INSERT INTO inventory_materials (id, item_code, name_km, name_en, unit, "
                "icon_key, prep_role) VALUES (gen_random_uuid(), "
                "'material_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8), "
                ":km, :en, 'm2', :icon, 'packaging') RETURNING id, item_code"
            ),
            {"icon": icon_key, "en": name_en, "km": name_km},
        ).one()
        material_id, item_code = row
        for code in (item_code, f"{item_code}_prepared"):
            bind.execute(
                sa.text(
                    "INSERT INTO inventory_balances (item_code, m2) VALUES (:code, 0) "
                    "ON CONFLICT (item_code) DO NOTHING"
                ),
                {"code": code},
            )
        bind.execute(
            sa.text(
                "INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details) "
                "VALUES (NULL, 'material.create', 'material', :id, "
                "jsonb_build_object('item_code', CAST(:code AS text), 'name_en', "
                "CAST(:en AS text), 'name_km', CAST(:km AS text), 'unit', 'm2', "
                "'source', 'seed'))"
            ),
            {"id": material_id, "code": item_code, "en": name_en, "km": name_km},
        )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        "DELETE FROM preparation_lines WHERE unit = 'm2' OR material_id IN "
        "(SELECT id FROM inventory_materials WHERE unit = 'm2')"
    )
    op.execute(
        "DELETE FROM inventory_movements WHERE m2_delta IS NOT NULL OR item_code IN "
        "(SELECT item_code FROM inventory_materials WHERE unit = 'm2') OR item_code IN "
        "(SELECT item_code || '_prepared' FROM inventory_materials WHERE unit = 'm2')"
    )
    op.execute(
        "DELETE FROM inventory_balances WHERE m2 IS NOT NULL OR item_code IN "
        "(SELECT item_code FROM inventory_materials WHERE unit = 'm2') OR item_code IN "
        "(SELECT item_code || '_prepared' FROM inventory_materials WHERE unit = 'm2')"
    )
    op.execute("DELETE FROM inventory_materials WHERE unit = 'm2'")
    for old_km, old_en, new_km, new_en in RENAMES:
        bind.execute(
            sa.text(
                "UPDATE inventory_materials SET name_km = :old_km, name_en = :old_en "
                "WHERE name_km = :new_km AND name_en = :new_en"
            ),
            {"new_km": new_km, "new_en": new_en, "old_km": old_km, "old_en": old_en},
        )
    op.drop_constraint("ck_preparation_lines_unit", "preparation_lines", type_="check")
    op.create_check_constraint(
        "ck_preparation_lines_unit",
        "preparation_lines",
        "unit IS NULL OR unit IN ('kg', 'g', 'count')",
    )
    op.drop_constraint("ck_inventory_materials_unit", "inventory_materials", type_="check")
    op.create_check_constraint(
        "ck_inventory_materials_unit", "inventory_materials", "unit IN ('kg', 'g', 'count')"
    )
    t = "inventory_movements"
    op.drop_constraint(f"ck_{t}_has_delta", t, type_="check")
    op.create_check_constraint(
        f"ck_{t}_has_delta",
        t,
        "count_delta IS NOT NULL OR kg_delta IS NOT NULL OR g_delta IS NOT NULL",
    )
    op.drop_column(t, "balance_m2_after")
    op.drop_column(t, "m2_delta")
    op.drop_constraint("ck_inventory_balances_m2", "inventory_balances", type_="check")
    op.drop_column("inventory_balances", "m2")
