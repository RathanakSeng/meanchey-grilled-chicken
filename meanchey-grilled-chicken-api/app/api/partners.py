"""Router factory for partner lists. `build_router(kind)` is mounted once per list."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.phones import format_phone
from app.deps import SessionDep, require_permission
from app.models import PartnerMixin, User
from app.schemas.common import UserRef
from app.schemas.partner import (
    PartnerCreate,
    PartnerOut,
    PartnerPage,
    PartnerSort,
    PartnerStats,
    PartnerStatus,
    PartnerUpdate,
)
from app.services import partner_service as svc
from app.services.partner_service import CUSTOMERS, SUPPLIERS, PartnerKind


def _ref(users: dict[uuid.UUID, User], user_id: uuid.UUID | None) -> UserRef | None:
    user = users.get(user_id) if user_id else None
    return UserRef.model_validate(user) if user else None


def _out(row: PartnerMixin, users: dict[uuid.UUID, User]) -> PartnerOut:
    return PartnerOut(
        id=row.id,
        name=row.name,
        location=row.location,
        phone=row.phone,
        phone_display=format_phone(row.phone),
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
        deleted_at=row.deleted_at,
        created_by=_ref(users, row.created_by),
        updated_by=_ref(users, row.updated_by),
    )


def build_router(kind: PartnerKind) -> APIRouter:
    router = APIRouter(prefix=f"/{kind.prefix}", tags=[kind.prefix])

    CanView = Annotated[User, Depends(require_permission(f"{kind.prefix}.view"))]
    CanCreate = Annotated[User, Depends(require_permission(f"{kind.prefix}.create"))]
    CanUpdate = Annotated[User, Depends(require_permission(f"{kind.prefix}.update"))]
    CanDelete = Annotated[User, Depends(require_permission(f"{kind.prefix}.delete"))]

    async def _one(session: SessionDep, row: PartnerMixin) -> PartnerOut:
        return _out(row, await svc.user_refs(session, [row]))

    @router.get("", response_model=PartnerPage, name=f"list_{kind.prefix}")
    async def list_partners(
        _: CanView,
        session: SessionDep,
        q: Annotated[str | None, Query(max_length=100)] = None,
        status: PartnerStatus = "active",
        sort: PartnerSort = "name",
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> PartnerPage:
        """`q` matches name and location (case-insensitive) and phone digits."""
        items, total = await svc.list_partners(
            session, kind, q=q, status=status, sort=sort, page=page, page_size=page_size
        )
        users = await svc.user_refs(session, items)
        return PartnerPage(
            items=[_out(r, users) for r in items], total=total, page=page, page_size=page_size
        )

    # Declared before /{partner_id} so "stats" isn't parsed as a UUID.
    @router.get("/stats", response_model=PartnerStats, name=f"{kind.prefix}_stats")
    async def get_stats(_: CanView, session: SessionDep) -> PartnerStats:
        """KPI figures. "This month" is the calendar month in BUSINESS_TIMEZONE."""
        return await svc.stats(session, kind)

    @router.post(
        "",
        response_model=PartnerOut,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{kind.entity}",
    )
    async def create_partner(
        body: PartnerCreate, actor: CanCreate, session: SessionDep
    ) -> PartnerOut:
        return await _one(session, await svc.create_partner(session, kind, actor, body))

    @router.get("/{partner_id}", response_model=PartnerOut, name=f"get_{kind.entity}")
    async def get_partner(partner_id: uuid.UUID, _: CanView, session: SessionDep) -> PartnerOut:
        return await _one(session, await svc.get_or_404(session, kind, partner_id))

    @router.patch("/{partner_id}", response_model=PartnerOut, name=f"update_{kind.entity}")
    async def update_partner(
        partner_id: uuid.UUID, body: PartnerUpdate, actor: CanUpdate, session: SessionDep
    ) -> PartnerOut:
        row = await svc.get_or_404(session, kind, partner_id)
        return await _one(session, await svc.update_partner(session, kind, actor, row, body))

    @router.post(
        "/{partner_id}/deactivate", response_model=PartnerOut, name=f"deactivate_{kind.entity}"
    )
    async def deactivate_partner(
        partner_id: uuid.UUID, actor: CanDelete, session: SessionDep
    ) -> PartnerOut:
        row = await svc.get_or_404(session, kind, partner_id)
        return await _one(session, await svc.deactivate_partner(session, kind, actor, row))

    @router.post(
        "/{partner_id}/reactivate", response_model=PartnerOut, name=f"reactivate_{kind.entity}"
    )
    async def reactivate_partner(
        partner_id: uuid.UUID, actor: CanDelete, session: SessionDep
    ) -> PartnerOut:
        row = await svc.get_or_404(session, kind, partner_id)
        return await _one(session, await svc.reactivate_partner(session, kind, actor, row))

    return router


suppliers_router = build_router(SUPPLIERS)
customers_router = build_router(CUSTOMERS)
