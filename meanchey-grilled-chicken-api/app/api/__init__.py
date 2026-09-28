from fastapi import APIRouter

from app.api import audit, auth, me, permissions, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(users.router)
api_router.include_router(permissions.router)
api_router.include_router(audit.router)
