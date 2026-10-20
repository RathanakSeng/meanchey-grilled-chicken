"""workplaces: Record level (attendance.workplace_update)

`attendance_workplace` gains a Record level between View only and Full access: editing existing
workplaces (name, address, position, radius) moves to the new `attendance.workplace_update`;
`attendance.workplace_manage` keeps create, delete / archive, restore and the default. Full is now
view + update + manage, so every user holding `workplace_manage` also gets `workplace_update`
(same `granted_by`) and stays at Full. The permission row is inserted here; the startup sync fills
the rest. One `permission.grant` audit entry per new grant, no actor,
`details.source = "default_change"`. The GM default stays View only.

Downgrade removes the `workplace_update` grants and the permission row.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (code, module, name_en, name_km, description_en, description_km,
            assignable_to, is_active)
        VALUES ('attendance.workplace_update', 'attendance', 'Edit workplaces',
            'កែកន្លែងធ្វើការ',
            'Edit existing workplaces: name, address, position on the map and check-in radius.',
            'កែកន្លែងធ្វើការដែលមានស្រាប់៖ ឈ្មោះ អាសយដ្ឋាន ទីតាំងលើផែនទី និងរង្វង់ចុះវត្តមាន។',
            ARRAY['general_manager'], true)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        WITH granted AS (
            INSERT INTO user_permissions (user_id, permission_code, granted_by)
            SELECT user_id, 'attendance.workplace_update', granted_by FROM user_permissions
            WHERE permission_code = 'attendance.workplace_manage'
            ON CONFLICT DO NOTHING
            RETURNING user_id
        )
        INSERT INTO audit_logs (actor_id, action, target_user_id, details)
        SELECT NULL, 'permission.grant', user_id, jsonb_build_object(
            'permission', 'attendance.workplace_update',
            'source', 'default_change'
        )
        FROM granted
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_permissions WHERE permission_code = 'attendance.workplace_update'")
    op.execute("DELETE FROM permissions WHERE code = 'attendance.workplace_update'")
