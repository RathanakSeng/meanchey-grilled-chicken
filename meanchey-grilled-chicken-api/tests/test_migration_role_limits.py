"""Migration 0008: role limits seeded, single-GM index dropped, over-limit data kept."""

import asyncio
import uuid

from alembic import command

from tests.test_migration_step_dates import _alembic, _run


def test_role_limits_migration() -> None:
    _alembic(command.downgrade, "0007")
    try:
        # Four active supervisors: already above the seeded limit of 3.
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, full_name, telegram_username, password_hash) VALUES "
                + ", ".join(
                    f"('{uuid.uuid4()}', 'supervisor', 'Sup {n}', 'mig_sup_{n}', 'x')"
                    for n in range(4)
                )
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    limits = asyncio.run(_run("SELECT role, max_active FROM role_limits ORDER BY role"))
    assert limits == [("general_manager", 2), ("staff", 10), ("supervisor", 3)]
    indexes = asyncio.run(_run("SELECT indexname FROM pg_indexes WHERE tablename = 'users'"))
    assert "uq_users_single_active_gm" not in {i for (i,) in indexes}
    kept = asyncio.run(_run("SELECT count(*) FROM users WHERE role = 'supervisor' AND is_active"))
    assert kept == [(4,)]
    asyncio.run(_run("DELETE FROM users WHERE telegram_username LIKE 'mig_sup_%'"))
