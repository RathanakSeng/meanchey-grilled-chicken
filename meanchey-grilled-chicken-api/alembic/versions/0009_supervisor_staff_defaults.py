"""supervisors: staff management Full -> View only (new default)

Supervisors now view staff and set their access (users.manage_access, granted by the startup
backfill) by default; adding (users.create) and editing (users.update) staff are the general
manager's to allow. Every supervisor whose staff management is exactly Full (users.view,
users.create, users.update) loses users.create and users.update. Supervisors at a custom or lower
level are left alone; deactivated ones are included, so reactivating doesn't bring Full back.

One `feature.set` audit entry per changed supervisor, with no actor (System) and
`details.source = "default_change"`. Downgrade does nothing: a removed grant can't be told apart
from a later manual change.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _staff_full ON COMMIT DROP AS
        SELECT u.id
        FROM users u
        JOIN user_permissions p ON p.user_id = u.id
        WHERE u.role = 'supervisor'
          AND p.permission_code IN ('users.view', 'users.create', 'users.update')
        GROUP BY u.id
        HAVING count(*) = 3
        """
    )
    op.execute(
        """
        DELETE FROM user_permissions
        WHERE user_id IN (SELECT id FROM _staff_full)
          AND permission_code IN ('users.create', 'users.update')
        """
    )
    op.execute(
        """
        INSERT INTO audit_logs (actor_id, action, target_user_id, details)
        SELECT NULL, 'feature.set', id, jsonb_build_object(
            'feature', 'staff_management',
            'from', 'full',
            'to', 'view',
            'added', '[]'::jsonb,
            'removed', '["users.create", "users.update"]'::jsonb,
            'source', 'default_change'
        )
        FROM _staff_full
        """
    )
    op.execute("DROP TABLE _staff_full")


def downgrade() -> None:
    pass
