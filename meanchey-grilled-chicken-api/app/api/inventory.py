"""Inventory: balances, per-batch breakdown, the movement history (inventory.history) and
materials (services/material_service.py)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.deps import SessionDep, require_permission
from app.inventory.catalog import Section
from app.models import User
from app.permissions.service import effective_permissions
from app.schemas.inventory import (
    InventoryItemDetailOut,
    InventoryItemOut,
    InventoryOut,
    MovementPage,
    MovementSource,
    SetValueIn,
)
from app.schemas.material import (
    MaterialCreate,
    MaterialOut,
    MaterialUpdate,
    StockAddIn,
    StockRemoveIn,
)
from app.services import inventory_service as svc
from app.services import material_service

router = APIRouter(prefix="/inventory", tags=["inventory"])

CanView = Annotated[User, Depends(require_permission("inventory.view"))]
CanSeeHistory = Annotated[User, Depends(require_permission("inventory.history"))]
CanStock = Annotated[User, Depends(require_permission("inventory.materials_stock"))]
CanManage = Annotated[User, Depends(require_permission("inventory.materials_manage"))]


@router.get("", response_model=InventoryOut)
async def overview(_: CanView, session: SessionDep) -> InventoryOut:
    """Every catalog item's balance and every active material (Raw, after Chicken), grouped by
    section (stock, then wasted)."""
    return await svc.overview(session)


@router.get("/items/{item_code}", response_model=InventoryItemDetailOut)
async def item_detail(item_code: str, _: CanView, session: SessionDep) -> InventoryItemDetailOut:
    """The item, its balance and `sources`: what each batch currently contributes (net, non-zero,
    oldest batch first; adds up to the balance). No movement details (inventory.history)."""
    return await svc.item_detail(session, item_code)


@router.get("/movements", response_model=MovementPage)
async def movements(
    _: CanSeeHistory,
    session: SessionDep,
    item_code: Annotated[str | None, Query(max_length=64)] = None,
    section: Section | None = None,
    source: MovementSource | None = None,
    batch_id: uuid.UUID | None = None,
    batch_code: Annotated[str | None, Query(max_length=32)] = None,
    order_id: uuid.UUID | None = None,
    preparation_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = svc.MOVEMENTS_PAGE_SIZE,
) -> MovementPage:
    """Newest first. Dates are business days (BUSINESS_TIMEZONE); `batch_code` matches part of
    the batch code; `order_id`: the movements of one order (delivery and return);
    `preparation_id`: one preparation's."""
    return await svc.movements(
        session,
        item_code=item_code,
        section=section,
        source=source,
        batch_id=batch_id,
        batch_code=batch_code,
        order_id=order_id,
        preparation_id=preparation_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.post("/items/{item_code}/set", response_model=InventoryItemOut)
async def set_value(
    item_code: str, body: SetValueIn, actor: CanView, session: SessionDep
) -> InventoryItemOut:
    """Refused for every item and everyone: production items change only through production
    (409 INVENTORY_ITEM_PRODUCTION_ONLY), materials through `/inventory/materials/{id}/add` and
    `/remove` (the same code, `details.use = "material_add_remove"`)."""
    await svc.set_value(session, actor, item_code, body)
    raise AssertionError("unreachable")


# --- Materials -----------------------------------------------------------------------------------


@router.get("/materials", response_model=list[MaterialOut])
async def list_materials(
    actor: CanView, session: SessionDep, include_archived: bool = False
) -> list[MaterialOut]:
    """Active materials by English name. `include_archived`: archived ones too (after them), only
    for holders of inventory.materials_manage (ignored for anyone else)."""
    manage = "inventory.materials_manage" in await effective_permissions(session, actor)
    return await material_service.list_materials(
        session, include_archived=include_archived and manage
    )


@router.post("/materials", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
async def create_material(
    body: MaterialCreate, actor: CanManage, session: SessionDep
) -> MaterialOut:
    """Names unique among active materials (DUPLICATE_MATERIAL_NAME); starts at 0."""
    material = await material_service.create_material(session, actor, body)
    return await material_service.material_out(session, material)


@router.patch("/materials/{material_id}", response_model=MaterialOut)
async def update_material(
    material_id: uuid.UUID, body: MaterialUpdate, actor: CanManage, session: SessionDep
) -> MaterialOut:
    """Names and unit. kg <-> g converts the balance; to / from count only before the first
    movement (MATERIAL_UNIT_LOCKED); system materials never to count (MATERIAL_SYSTEM_LOCKED)."""
    material = await material_service.update_material(session, actor, material_id, body)
    return await material_service.material_out(session, material)


@router.post("/materials/{material_id}/archive", response_model=MaterialOut)
async def archive_material(
    material_id: uuid.UUID, actor: CanManage, session: SessionDep
) -> MaterialOut:
    """Hidden from Raw and pickers; balance and history kept. System materials → 409
    MATERIAL_SYSTEM_LOCKED."""
    material = await material_service.archive_material(session, actor, material_id)
    return await material_service.material_out(session, material)


@router.post("/materials/{material_id}/restore", response_model=MaterialOut)
async def restore_material(
    material_id: uuid.UUID, actor: CanManage, session: SessionDep
) -> MaterialOut:
    """Back in Raw (its names must still be free among active materials)."""
    material = await material_service.restore_material(session, actor, material_id)
    return await material_service.material_out(session, material)


@router.get(
    "/materials/{material_id}/icon",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_material_icon(material_id: uuid.UUID, _: CanView, session: SessionDep) -> Response:
    """The uploaded icon (PNG). 404 NOT_FOUND without one. The URL in `icon_url` is versioned, so
    it may be cached for a long time."""
    data, mime = await material_service.get_icon(session, material_id)
    return Response(
        data, media_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"}
    )


@router.put("/materials/{material_id}/icon", response_model=MaterialOut)
async def upload_material_icon(
    material_id: uuid.UUID,
    actor: CanManage,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, at most 1 MB")],
) -> MaterialOut:
    """Multipart upload (`file`). Not a PNG / JPEG / WebP or over 1 MB → VALIDATION_ERROR.
    Stored as a 256 px square PNG (center-cropped); replaces any earlier upload."""
    data = await file.read(material_service.ICON_MAX_BYTES + 1)
    material = await material_service.set_icon(session, actor, material_id, data)
    return await material_service.material_out(session, material)


@router.delete("/materials/{material_id}/icon", response_model=MaterialOut)
async def delete_material_icon(
    material_id: uuid.UUID, actor: CanManage, session: SessionDep
) -> MaterialOut:
    """Removes the uploaded icon (the bundled picture or the unit icon shows again)."""
    material = await material_service.delete_icon(session, actor, material_id)
    return await material_service.material_out(session, material)


@router.post("/materials/{material_id}/add", response_model=MaterialOut)
async def add_stock(
    material_id: uuid.UUID, body: StockAddIn, actor: CanStock, session: SessionDep
) -> MaterialOut:
    """`quantity` > 0 in the material's unit (count whole, kg 3 decimals, g 1 decimal)."""
    material = await material_service.add_stock(session, actor, material_id, body)
    return await material_service.material_out(session, material)


@router.post("/materials/{material_id}/remove", response_model=MaterialOut)
async def remove_stock(
    material_id: uuid.UUID, body: StockRemoveIn, actor: CanStock, session: SessionDep
) -> MaterialOut:
    """`quantity` > 0 and a `reason`; can't go below 0 (INVENTORY_INSUFFICIENT)."""
    material = await material_service.remove_stock(session, actor, material_id, body)
    return await material_service.material_out(session, material)
