"""The signed-in user's own notifications (the bell)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.deps import CurrentUser, SessionDep
from app.schemas.notification import NotificationOut, NotificationPage, ReadAllOut
from app.services import notification_service as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    user: CurrentUser,
    session: SessionDep,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NotificationPage:
    """Newest first; `unread_count` counts all unread ones, whatever the page."""
    return await svc.list_own(
        session, user, unread_only=unread_only, page=page, page_size=page_size
    )


@router.post("/read-all", response_model=ReadAllOut)
async def read_all(user: CurrentUser, session: SessionDep) -> ReadAllOut:
    updated = await svc.mark_all_read(session, user)
    return ReadAllOut(updated=updated, unread_count=await svc.unread_count(session, user))


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def read_one(
    notification_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> NotificationOut:
    """Someone else's notification answers 404 NOTIFICATION_NOT_FOUND."""
    return await svc.mark_read(session, user, notification_id)
