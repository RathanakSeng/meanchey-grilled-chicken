"""Packaging plans (see services/plan_service.py for the rules)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import SessionDep, require_permission
from app.models import User
from app.schemas.production import PlanDetail, PlanListStatus, PlanPage, PlanUpdate, VersionIn
from app.services import plan_service
from app.services import production_service as prod

router = APIRouter(prefix="/production-plans", tags=["production-plans"])

CanView = Annotated[User, Depends(require_permission("production_plan.view"))]
CanManage = Annotated[User, Depends(require_permission("production_plan.manage"))]


@router.get("", response_model=PlanPage)
async def list_plans(
    _: CanView,
    session: SessionDep,
    status: PlanListStatus = "pending",
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PlanPage:
    """`pending`: waiting for a plan (default); `confirmed`: step 3 not finished yet;
    `completed`: batch completed; `all`: every plan of a batch that isn't cancelled.
    `pending_count` is the number waiting, whatever the filter."""
    return await plan_service.list_plans(
        session, status=status, q=q, page=page, page_size=page_size
    )


@router.get("/{batch_id}", response_model=PlanDetail)
async def get_plan(batch_id: uuid.UUID, _: CanView, session: SessionDep) -> PlanDetail:
    """The plan with the step 2 output it is based on, and the batch version for writes."""
    return await plan_service.plan_detail(session, await prod.get_batch(session, batch_id))


@router.patch("/{batch_id}", response_model=PlanDetail)
async def update_plan(
    batch_id: uuid.UUID, body: PlanUpdate, actor: CanManage, session: SessionDep
) -> PlanDetail:
    """Partial save; `version` is the batch version. A confirmed plan stays confirmed."""
    batch = await plan_service.update_plan(session, actor, batch_id, body)
    return await plan_service.plan_detail(session, batch)


@router.post("/{batch_id}/confirm", response_model=PlanDetail)
async def confirm_plan(
    batch_id: uuid.UUID, body: VersionIn, actor: CanManage, session: SessionDep
) -> PlanDetail:
    """Both pack counts are required; step 3 can start once the plan is confirmed."""
    batch = await plan_service.confirm_plan(session, actor, batch_id, body.version)
    return await plan_service.plan_detail(session, batch)
