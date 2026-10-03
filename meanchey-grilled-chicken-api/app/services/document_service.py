"""Delivery notes: an order → PDF (download or the requester's Telegram chat), and the preview.

- **Any status** (Created onward, Cancelled included) for anyone with `orders.view`.
- **Original and copies:** each generated note increments `orders.print_count` (an atomic
  `UPDATE … RETURNING`, which also locks the order row until the commit, so two prints can't both
  be the original). The first is the original; later ones say COPY #n. Printing doesn't change the
  order's `version`. Each one writes `order.document_printed` (`copy`, `via`: download / telegram).
  If rendering or sending fails, the transaction rolls back: nothing is counted.
- **Names** come from `OrderOut` dumped in the request, so they follow the viewer's redaction
  (the superadmin reads as "System").
- **Preview** (Business info): the latest order when the requester can see orders, otherwise a
  made-up one; always marked SAMPLE, never counted or audited.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.notify import mini_app_link
from app.config import get_settings
from app.documents.delivery_note import build_context, sample_order
from app.documents.render import render_pdf
from app.models import Order, User, utcnow
from app.permissions.service import effective_permissions
from app.services import business_service, order_service
from app.services.audit_service import record

Via = Literal["download", "telegram"]


async def _business(session: AsyncSession) -> tuple[dict[str, Any], tuple[bytes, str] | None]:
    row = await business_service.get_row(session, with_logo=True)
    out = await business_service.business_out(session, row)
    logo = (row.logo, row.logo_mime) if row.logo is not None and row.logo_mime else None
    return out.model_dump(mode="json"), logo


async def _render(
    session: AsyncSession,
    order: dict[str, Any],
    order_id: uuid.UUID | None,
    *,
    copy: int | None,
    sample: bool = False,
) -> bytes:
    business, logo = await _business(session)
    context = build_context(
        order,
        business,
        printed_at=utcnow().astimezone(get_settings().business_tz),
        copy=copy,
        app_url=mini_app_link(f"/workstation/orders/{order_id}") if order_id else None,
        logo=logo,
        sample=sample,
    )
    return await render_pdf(context)


async def print_order(
    session: AsyncSession, actor: User, order_id: uuid.UUID, via: Via
) -> tuple[Order, bytes, int]:
    """Count, render and audit one delivery note. Returns (order, pdf, copy number). The caller
    commits (after sending it, for Telegram) or rolls back."""
    await order_service.get_order(session, order_id)  # ORDER_NOT_FOUND
    number = (
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(print_count=Order.print_count + 1)
            .returning(Order.print_count)
        )
    ).scalar_one()
    order = await order_service.get_order(session, order_id)
    data = (await order_service.order_out(session, order)).model_dump(mode="json")
    pdf = await _render(session, data, order.id, copy=number if number > 1 else None)
    record(
        session,
        "order.document_printed",
        actor_id=actor.id,
        entity_type=order_service.ENTITY,
        entity_id=order.id,
        details={"code": order.code, "copy": number, "via": via},
    )
    return order, pdf, number


async def preview(session: AsyncSession, viewer: User) -> bytes:
    order = None
    if "orders.view" in await effective_permissions(session, viewer):
        order = await session.scalar(
            select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(1)
        )
    if order is None:
        return await _render(session, sample_order(), None, copy=None, sample=True)
    data = (await order_service.order_out(session, order)).model_dump(mode="json")
    return await _render(session, data, order.id, copy=None, sample=True)
