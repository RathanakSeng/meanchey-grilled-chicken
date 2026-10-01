"""inventory: production items only — remove adjustments, recompute balances

Every inventory item now changes only through production. This one-time reset:

- deletes every `source = 'adjustment'` movement (the `inventory.adjust` audit entries stay as
  the record of what was done);
- recomputes each remaining movement's `balance_count_after` / `balance_kg_after` as a running
  total per item (ordered by `created_at`, `id`);
- sets `inventory_balances` to the per-item totals (a unit an item doesn't track stays null).

Inventory therefore reflects production only. Running it again changes nothing. If production
alone would leave an item below zero (only possible when an adjustment had covered more by-product
than the batches produced), it stops with an error instead of writing a negative balance.
Downgrade does nothing: deleted adjustments can't be restored.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("DELETE FROM inventory_movements WHERE source = 'adjustment'")

    negative = bind.execute(
        sa.text(
            """
            SELECT b.item_code
            FROM inventory_balances b
            JOIN inventory_movements m ON m.item_code = b.item_code
            GROUP BY b.item_code, b.count, b.kg
            HAVING (b.count IS NOT NULL AND SUM(COALESCE(m.count_delta, 0)) < 0)
                OR (b.kg IS NOT NULL AND SUM(COALESCE(m.kg_delta, 0)) < 0)
            """
        )
    ).scalars().all()
    if negative:
        raise RuntimeError(
            "Inventory reset: production alone leaves these items below zero: "
            + ", ".join(negative)
        )

    op.execute(
        """
        WITH running AS (
            SELECT m.id,
                   SUM(COALESCE(m.count_delta, 0)) OVER w AS count_after,
                   SUM(COALESCE(m.kg_delta, 0)) OVER w AS kg_after
            FROM inventory_movements m
            WINDOW w AS (
                PARTITION BY m.item_code ORDER BY m.created_at, m.id
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )
        )
        UPDATE inventory_movements m
        SET balance_count_after = CASE WHEN b.count IS NULL THEN NULL ELSE r.count_after END,
            balance_kg_after = CASE WHEN b.kg IS NULL THEN NULL ELSE r.kg_after END
        FROM running r, inventory_balances b
        WHERE m.id = r.id AND b.item_code = m.item_code
        """
    )
    op.execute(
        """
        UPDATE inventory_balances b
        SET count = CASE WHEN b.count IS NULL THEN NULL ELSE COALESCE(
                (SELECT SUM(m.count_delta) FROM inventory_movements m
                 WHERE m.item_code = b.item_code), 0) END,
            kg = CASE WHEN b.kg IS NULL THEN NULL ELSE COALESCE(
                (SELECT SUM(m.kg_delta) FROM inventory_movements m
                 WHERE m.item_code = b.item_code), 0) END
        """
    )


def downgrade() -> None:
    pass
