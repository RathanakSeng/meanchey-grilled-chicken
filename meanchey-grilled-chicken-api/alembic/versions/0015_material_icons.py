"""material icons: inventory_materials.icon_key, icon (bytea) and icon_mime

- `icon_key`: a picture bundled with the UI (`string`, `skewer`, `marinade`...). Backfilled for
  the default materials by their English name (Marinade sauce by its system code).
- `icon` / `icon_mime`: an uploaded icon (a 256 px square PNG), both set or both null.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "inventory_materials"
# Default materials (services/material_service.DEFAULTS) -> bundled picture.
ICON_KEYS = {
    "String": "string",
    "Skewer": "skewer",
    "Sticker (2-piece packs)": "sticker_2",
    "Sticker (4-piece packs)": "sticker_4",
    "Satay sauce": "satay",
    "Zip bag 7 (2-piece packs)": "zip_bag_2",
    "Zip bag 7 (4-piece packs)": "zip_bag_4",
    "Vacuum bag": "vacuum_bag",
}


def upgrade() -> None:
    op.add_column(T, sa.Column("icon_key", sa.String(32), nullable=True))
    op.add_column(T, sa.Column("icon", sa.LargeBinary(), nullable=True))
    op.add_column(T, sa.Column("icon_mime", sa.String(16), nullable=True))
    op.create_check_constraint(f"ck_{T}_icon_mime", T, "(icon IS NULL) = (icon_mime IS NULL)")
    materials = sa.table(
        T, sa.column("name_en", sa.String), sa.column("system_code", sa.String),
        sa.column("icon_key", sa.String),
    )
    op.execute(
        materials.update().where(materials.c.system_code == "marinade").values(icon_key="marinade")
    )
    for name_en, key in ICON_KEYS.items():
        op.execute(
            materials.update()
            .where(sa.func.lower(materials.c.name_en) == name_en.lower())
            .where(materials.c.system_code.is_(None))
            .values(icon_key=key)
        )


def downgrade() -> None:
    op.drop_constraint(f"ck_{T}_icon_mime", T, type_="check")
    op.drop_column(T, "icon_mime")
    op.drop_column(T, "icon")
    op.drop_column(T, "icon_key")
