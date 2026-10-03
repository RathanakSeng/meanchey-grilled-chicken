"""System settings: role limits (superadmin only) and business info (`settings.business_info`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.api.orders import pdf_response
from app.core.errors import AppError, ErrorCode
from app.deps import SessionDep, require_permission, require_role
from app.models import Role, User
from app.schemas.business import BusinessIn, BusinessOut
from app.schemas.role_limit import RoleLimitIn, RoleLimitOut
from app.services import business_service, document_service, role_limit_service

router = APIRouter(prefix="/settings", tags=["settings"])

Superadmin = Annotated[User, Depends(require_role(Role.SUPERADMIN))]
# The superadmin holds it implicitly; a general manager only with the Business info feature.
CanEditBusiness = Annotated[User, Depends(require_permission("settings.business_info"))]


@router.get("/role-limits", response_model=list[RoleLimitOut])
async def list_role_limits(_: Superadmin, session: SessionDep) -> list[RoleLimitOut]:
    """Limit, active count and over-limit flag for general managers, supervisors and staff."""
    return await role_limit_service.list_limits(session)


@router.put("/role-limits/{role}", response_model=list[RoleLimitOut])
async def set_role_limit(
    role: Role, body: RoleLimitIn, actor: Superadmin, session: SessionDep
) -> list[RoleLimitOut]:
    """1–999, or null = unlimited (supervisor, staff). Lowering below the active count keeps
    everyone active; the role is full until enough users leave it."""
    return await role_limit_service.set_limit(session, actor, role, body.max_active)


@router.get("/business", response_model=BusinessOut)
async def get_business(_: CanEditBusiness, session: SessionDep) -> BusinessOut:
    """What delivery notes print at the top and bottom."""
    return await business_service.business_out(session, await business_service.get_row(session))


@router.put("/business", response_model=BusinessOut)
async def update_business(
    body: BusinessIn, actor: CanEditBusiness, session: SessionDep
) -> BusinessOut:
    """Replaces every text field. Names required; phone normalized (INVALID_PHONE)."""
    row = await business_service.update(session, actor, body)
    return await business_service.business_out(session, row)


@router.get(
    "/business/logo",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def get_business_logo(_: CanEditBusiness, session: SessionDep) -> Response:
    row = await business_service.get_row(session, with_logo=True)
    if row.logo is None or row.logo_mime is None:
        raise AppError(404, ErrorCode.NOT_FOUND, "No logo")
    return Response(row.logo, media_type=row.logo_mime, headers={"Cache-Control": "no-store"})


@router.put("/business/logo", response_model=BusinessOut)
async def upload_business_logo(
    actor: CanEditBusiness,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="PNG or JPEG, at most 500 kB")],
) -> BusinessOut:
    """Multipart upload (`file`). Not a PNG/JPEG or over 500 kB → VALIDATION_ERROR. Stored
    resized to at most 400 px wide."""
    data = await file.read(business_service.LOGO_MAX_BYTES + 1)
    row = await business_service.set_logo(session, actor, data)
    return await business_service.business_out(session, row)


@router.delete("/business/logo", response_model=BusinessOut)
async def delete_business_logo(actor: CanEditBusiness, session: SessionDep) -> BusinessOut:
    row = await business_service.delete_logo(session, actor)
    return await business_service.business_out(session, row)


@router.get(
    "/business/preview.pdf",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def preview_business_document(actor: CanEditBusiness, session: SessionDep) -> Response:
    """A delivery note marked SAMPLE with the current business info: the latest order when the
    requester can see orders, otherwise made-up data. Not counted, not audited."""
    return pdf_response(await document_service.preview(session, actor), "preview.pdf")
