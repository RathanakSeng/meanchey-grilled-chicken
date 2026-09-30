import uuid

from pydantic import BaseModel, Field

from app.permissions.registry import Menu


class FeatureLevelOut(BaseModel):
    level: str
    # False when the viewer may not give this level: above a supervisor's own access.
    allowed: bool


class FeatureOut(BaseModel):
    code: str
    menu: Menu
    name_en: str
    name_km: str
    description_en: str
    description_km: str
    # Levels in order (always starts with "off").
    levels: list[FeatureLevelOut]
    # One of `levels`, or "custom" when the user's permissions match no level exactly.
    current_level: str
    can_edit: bool


class FeatureMenuOut(BaseModel):
    menu: Menu
    features: list[FeatureOut]


class UserFeaturesOut(BaseModel):
    user_id: uuid.UUID
    menus: list[FeatureMenuOut]


class FeatureLevelIn(BaseModel):
    # Plain string: the level is checked after scope and feature (see features.set_level), so an
    # out-of-scope caller learns nothing from the body. Known levels: registry.LEVELS.
    level: str = Field(min_length=1, max_length=16)
