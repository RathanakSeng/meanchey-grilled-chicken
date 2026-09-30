"""Migration 0009: supervisors at Full staff management land on View only (new default)."""

import asyncio
import uuid

from alembic import command

from tests.test_migration_step_dates import _alembic, _run

USERS = ("users.view", "users.create", "users.update")


def _grants(user_id: uuid.UUID, codes) -> str:
    return ", ".join(f"('{user_id}', '{c}')" for c in codes)


def test_supervisor_staff_defaults_migration() -> None:
    full, custom, view, gone, gm = (uuid.uuid4() for _ in range(5))
    rows = [
        (full, "supervisor", True, USERS),
        (custom, "supervisor", True, ("users.view", "users.update")),  # custom: left alone
        (view, "supervisor", True, ("users.view",)),
        (gone, "supervisor", False, USERS),  # deactivated: migrated too
        (gm, "general_manager", True, USERS),  # not a supervisor
    ]
    _alembic(command.downgrade, "0008")
    try:
        asyncio.run(
            _run(
                "INSERT INTO users (id, role, full_name, telegram_username, password_hash, "
                "is_active) VALUES "
                + ", ".join(
                    f"('{uid}', '{role}', 'Mig {n}', 'mig_staffdef_{n}', 'x', {active})"
                    for n, (uid, role, active, _) in enumerate(rows)
                ),
                "INSERT INTO user_permissions (user_id, permission_code) VALUES "
                + ", ".join(_grants(uid, codes) for uid, _, _, codes in rows),
            )
        )
    finally:
        _alembic(command.upgrade, "head")

    async def held() -> dict[uuid.UUID, set[str]]:
        out: dict[uuid.UUID, set[str]] = {}
        for uid, code in await _run(
            "SELECT user_id, permission_code FROM user_permissions WHERE user_id = ANY(:ids)",
            ids=[r[0] for r in rows],
        ):
            out.setdefault(uid, set()).add(code)
        return out

    async def logs() -> list:
        return await _run(
            "SELECT actor_id, target_user_id, details FROM audit_logs "
            "WHERE action = 'feature.set' AND target_user_id = ANY(:ids) ORDER BY id",
            ids=[r[0] for r in rows],
        )

    try:
        after = asyncio.run(held())
        assert after[full] == {"users.view"}
        assert after[gone] == {"users.view"}
        assert after[custom] == {"users.view", "users.update"}
        assert after[view] == {"users.view"}
        assert after[gm] == set(USERS)

        entries = asyncio.run(logs())
        assert {target for _, target, _ in entries} == {full, gone}
        for actor, _, details in entries:
            assert actor is None  # System
            assert details == {
                "feature": "staff_management",
                "from": "full",
                "to": "view",
                "added": [],
                "removed": ["users.create", "users.update"],
                "source": "default_change",
            }

        # Idempotent: running it again changes nothing and logs nothing.
        _alembic(command.downgrade, "0008")
        _alembic(command.upgrade, "head")
        assert asyncio.run(held()) == after
        assert len(asyncio.run(logs())) == 2
    finally:
        asyncio.run(
            _run(
                "DELETE FROM audit_logs WHERE target_user_id = ANY(:ids)",
                "DELETE FROM users WHERE telegram_username LIKE 'mig_staffdef_%'",
                ids=[r[0] for r in rows],
            )
        )
