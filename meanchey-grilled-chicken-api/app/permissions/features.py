"""Feature access levels: the general manager's view of permissions.

A feature (registry.FEATURES) maps each level (off / view / [record /] full) to an exact set of
permission codes. Setting a level grants and revokes only that feature's codes; everything else a
user holds is untouched. Detailed permissions stay the underlying mechanism (superadmin-only UI).

Whoever may manage access (`permissions.grant`: the general manager, and the superadmin) can set
ANY level of ANY feature that applies to a user they manage. Unlike detailed grants, it doesn't
matter which feature permissions the actor holds personally.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models import User, UserPermission
from app.permissions.hierarchy import can_manage
from app.permissions.registry import FEATURES, FEATURES_BY_CODE, FeatureDef
from app.permissions.service import GRANT_PERMISSION, effective_permissions
from app.services.audit_service import record

CUSTOM = "custom"


def current_level(feature: FeatureDef, held: set[str] | frozenset[str]) -> str:
    """The level whose codes exactly equal `held` restricted to the feature; else "custom"."""
    mine = frozenset(held) & feature.codes
    for level, codes in feature.level_map.items():
        if codes == mine:
            return level
    return CUSTOM


def features_for(target: User) -> list[FeatureDef]:
    return [f for f in FEATURES if target.role in f.applies_to]


@dataclass
class FeatureState:
    feature: FeatureDef
    current_level: str
    can_edit: bool


def _can_edit(actor_perms: set[str], actor: User, target: User) -> bool:
    """Every level of every applicable feature: the actor manages access and the target."""
    return GRANT_PERMISSION in actor_perms and can_manage(actor, target) and target.is_active


async def feature_matrix(session: AsyncSession, actor: User, target: User) -> list[FeatureState]:
    held = await effective_permissions(session, target)
    actor_perms = await effective_permissions(session, actor)
    return [
        FeatureState(
            feature=f,
            current_level=current_level(f, held),
            can_edit=_can_edit(actor_perms, actor, target),
        )
        for f in features_for(target)
    ]


async def set_level(
    session: AsyncSession, actor: User, target: User, feature_code: str, level: str
) -> FeatureState:
    """Set one feature's level for `target`. Checks, in order (after the route guard for
    `permissions.grant` and the hidden-account lookup):

    FORBIDDEN_SCOPE, FEATURE_NOT_FOUND, FEATURE_NOT_APPLICABLE, VALIDATION_ERROR (unknown level),
    USER_INACTIVE. The actor's own feature permissions are not checked.
    """
    if not can_manage(actor, target):
        raise AppError(403, ErrorCode.FORBIDDEN_SCOPE, "Target user is outside your scope")
    feature = FEATURES_BY_CODE.get(feature_code)
    if feature is None:
        raise AppError(404, ErrorCode.FEATURE_NOT_FOUND, f"Unknown feature {feature_code}")
    if target.role not in feature.applies_to:
        raise AppError(
            422, ErrorCode.FEATURE_NOT_APPLICABLE, "This feature can't be set for this user"
        )
    levels = feature.level_map
    if level not in levels:
        raise AppError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "Unknown level",
            {"fields": [{"loc": ["body", "level"], "type": "value_error", "msg": "Unknown level"}]},
        )
    desired = levels[level]
    if not target.is_active:
        raise AppError(409, ErrorCode.USER_INACTIVE, "User is deactivated")

    held_before = await effective_permissions(session, target)
    before = current_level(feature, held_before)
    # Raw rows within the feature (an ineffective leftover row is cleaned up too).
    stored = set(
        await session.scalars(
            select(UserPermission.permission_code).where(
                UserPermission.user_id == target.id,
                UserPermission.permission_code.in_(feature.codes),
            )
        )
    )
    added = sorted(desired - stored)
    removed = sorted(stored - desired)
    if not added and not removed:
        return FeatureState(feature, level, True)

    for code in added:
        await session.execute(
            pg_insert(UserPermission)
            .values(user_id=target.id, permission_code=code, granted_by=actor.id)
            .on_conflict_do_nothing()
        )
    if removed:
        await session.execute(
            delete(UserPermission).where(
                UserPermission.user_id == target.id,
                UserPermission.permission_code.in_(removed),
            )
        )
    # One entry for the whole change; no individual permission.grant/revoke entries.
    record(
        session,
        "feature.set",
        actor_id=actor.id,
        target_user_id=target.id,
        details={
            "feature": feature.code,
            "from": before,
            "to": level,
            "added": added,
            "removed": removed,
        },
    )
    await session.commit()
    return FeatureState(feature, level, True)
