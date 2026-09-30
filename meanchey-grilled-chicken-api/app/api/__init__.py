from fastapi import APIRouter

from app.api import (
    audit,
    auth,
    features,
    me,
    notifications,
    permissions,
    production,
    production_plans,
    users,
)
from app.api.partners import customers_router, suppliers_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(users.router)
api_router.include_router(permissions.router)
api_router.include_router(features.router)
api_router.include_router(audit.router)
api_router.include_router(suppliers_router)
api_router.include_router(customers_router)
api_router.include_router(production.router)
api_router.include_router(production_plans.router)
api_router.include_router(notifications.router)
