import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import SessionDep, require_permission
from app.models import User
from app.permissions import features as feature_service
from app.permissions.hierarchy import ensure_can_manage
from app.permissions.registry import MENUS
from app.schemas.feature import FeatureLevelIn, FeatureMenuOut, FeatureOut, UserFeaturesOut
from app.services.user_service import get_user_or_404

router = APIRouter(tags=["features"])

CanManageFeatures = Annotated[User, Depends(require_permission("permissions.grant"))]


def _out(state: feature_service.FeatureState) -> FeatureOut:
    f = state.feature
    return FeatureOut(
        code=f.code,
        menu=f.menu,
        name_en=f.name_en,
        name_km=f.name_km,
        description_en=f.description_en,
        description_km=f.description_km,
        levels=[level for level, _ in f.levels],
        current_level=state.current_level,
        can_edit=state.can_edit,
    )


@router.get("/users/{user_id}/features", response_model=UserFeaturesOut)
async def get_user_features(
    user_id: uuid.UUID, actor: CanManageFeatures, session: SessionDep
) -> UserFeaturesOut:
    """Feature access levels that apply to the user's role, grouped by menu."""
    target = await get_user_or_404(session, user_id, actor)
    ensure_can_manage(actor, target)
    states = await feature_service.feature_matrix(session, actor, target)
    menus = [
        FeatureMenuOut(menu=menu, features=[_out(s) for s in states if s.feature.menu == menu])
        for menu in MENUS
    ]
    return UserFeaturesOut(user_id=target.id, menus=[m for m in menus if m.features])


@router.put("/users/{user_id}/features/{feature}", response_model=FeatureOut)
async def set_user_feature(
    user_id: uuid.UUID,
    feature: str,
    body: FeatureLevelIn,
    actor: CanManageFeatures,
    session: SessionDep,
) -> FeatureOut:
    """Set Off / View only / Full access. Only the feature's own permissions change."""
    target = await get_user_or_404(session, user_id, actor)
    state = await feature_service.set_level(session, actor, target, feature, body.level)
    return _out(state)
