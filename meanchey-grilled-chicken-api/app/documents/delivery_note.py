"""What the delivery note shows: an order (as the API serializes it) → the template's context.

Kept free of WeasyPrint so it can be tested anywhere; `render.py` turns the context into a PDF.

**Prices later.** The document kind decides the title and whether prices show, in one place
(`kind_for`). Lines and totals already carry `unit_price` / `amount` (None today) and the template
has the columns behind `kind.show_prices`. When orders get prices, `kind_for` returns `INVOICE`
for priced orders and the same template prints វិក្កយបត្រ / INVOICE with the money columns.
"""

import base64
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.inventory.catalog import PACKS_BIG, PACKS_SMALL, byproduct_packed
from app.production.catalog import BYPRODUCTS


@dataclass(frozen=True)
class DocumentKind:
    code: str
    title_km: str
    title_en: str
    show_prices: bool


DELIVERY_NOTE = DocumentKind("delivery_note", "ប័ណ្ណដឹកជញ្ជូន", "DELIVERY NOTE", show_prices=False)
INVOICE = DocumentKind("invoice", "វិក្កយបត្រ", "INVOICE", show_prices=True)


def kind_for(order: dict[str, Any]) -> DocumentKind:
    """Orders have no prices yet: always a delivery note."""
    return DELIVERY_NOTE


# Every label of the document: Khmer, with the English under it.
LABELS: dict[str, tuple[str, str]] = {
    "customer": ("អតិថិជន", "Customer"),
    "phone": ("ទូរស័ព្ទ", "Phone"),
    "location": ("ទីតាំង", "Location"),
    "delivery_date": ("ថ្ងៃដឹកជញ្ជូន", "Delivery date"),
    "driver": ("អ្នកដឹកជញ្ជូន", "Driver"),
    "order": ("លេខបញ្ជាទិញ", "Order no."),
    "printed": ("បោះពុម្ព", "Printed"),
    "status": ("ស្ថានភាព", "Status"),
    "item": ("ទំនិញ", "Item"),
    "quantity": ("ចំនួន", "Qty"),
    "unit_price": ("តម្លៃ", "Price"),
    "amount": ("សរុប", "Amount"),
    "subtotal": ("សរុបរង", "Subtotal"),
    "box": ("ប្រអប់ទី", "Box"),
    "boxes": ("ប្រអប់", "Boxes"),
    "grand_total": ("សរុបទាំងអស់", "Grand total"),
    "money_total": ("ទឹកប្រាក់សរុប", "Total amount"),
    "returned": ("ទំនិញប្រគល់មកវិញ", "Returned"),
    "returned_qty": ("ប្រគល់វិញ", "Returned"),
    "to_stock": ("ចូលស្តុក", "To stock"),
    "to_wasted": ("ខូចខាត", "Wasted"),
    "reason": ("មូលហេតុ", "Reason"),
    "note": ("កំណត់សម្គាល់", "Note"),
    "prepared_by": ("រៀបចំដោយ", "Prepared by"),
    "received_by": ("អ្នកទទួល", "Received by"),
    "signature": ("ហត្ថលេខា", "Signature"),
    "date": ("កាលបរិច្ឆេទ", "Date"),
    "copy": ("ច្បាប់ចម្លង", "COPY"),
    "cancelled": ("បានលុបចោល", "CANCELLED"),
    "cancel_reason": ("មូលហេតុលុបចោល", "Cancel reason"),
    "scan": ("ស្កេនដើម្បីបើកក្នុងកម្មវិធី", "Scan to open in the app"),
    "sample": ("គំរូ", "SAMPLE"),
}

COLORS: dict[str, tuple[str, str]] = {
    "white": ("ប្រអប់ស", "White box"),
    "black": ("ប្រអប់ខ្មៅ", "Black box"),
}
COLOR_SECTIONS: dict[str, tuple[str, str]] = {
    "white": ("ប្រអប់ស", "White boxes"),
    "black": ("ប្រអប់ខ្មៅ", "Black boxes"),
}
STATUSES: dict[str, tuple[str, str]] = {
    "created": ("បានបង្កើត", "Created"),
    "delivering": ("កំពុងដឹកជញ្ជូន", "Delivering"),
    "return_pending": ("រង់ចាំពិនិត្យការប្រគល់វិញ", "Return pending"),
    "success": ("ជោគជ័យ", "Success"),
    "partly_returned": ("ប្រគល់មកវិញខ្លះ", "Partly returned"),
    "fully_returned": ("ប្រគល់មកវិញទាំងអស់", "Fully returned"),
    "cancelled": ("បានលុបចោល", "Cancelled"),
}

# Short item names for the narrow receipt ("Liver", not "Liver (packed)").
_SHORT_NAMES: dict[str, tuple[str, str]] = {
    PACKS_BIG: ("កញ្ចប់ ៤ ដុំ", "4-Piece Packs"),
    PACKS_SMALL: ("កញ្ចប់ ២ ដុំ", "2-Piece Packs"),
    **{byproduct_packed(b.code): (b.name_km, b.name_en) for b in BYPRODUCTS},
}


def short_name(item: dict[str, Any]) -> tuple[str, str]:
    return _SHORT_NAMES.get(item["item_code"], (item["name_km"], item["name_en"]))


def quantity_text(count: int | None, kg: Any) -> str:
    """Packs as a whole count, by-products as kg with 3 decimals."""
    if count is not None:
        return str(count)
    if kg is None:
        return "0"
    return f"{float(kg):.3f} kg"


def _line(item: dict[str, Any], count: int | None, kg: Any) -> dict[str, Any]:
    km, en = short_name(item)
    return {
        "name_km": km,
        "name_en": en,
        "quantity": quantity_text(count, kg),
        # Prices later (None until orders have them).
        "unit_price": item.get("unit_price"),
        "amount": item.get("amount"),
    }


def _items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_line(i, i.get("count"), i.get("kg")) for i in items]


def _day(value: str | date | None) -> str:
    if value is None:
        return ""
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return d.strftime("%d/%m/%Y")


def _name(ref: dict[str, Any] | None) -> str:
    return ref["full_name"] if ref else ""


def build_context(
    order: dict[str, Any],
    business: dict[str, Any],
    *,
    printed_at: datetime,
    copy: int | None,
    app_url: str | None,
    logo: tuple[bytes, str] | None,
    sample: bool = False,
) -> dict[str, Any]:
    """`order` is `OrderOut.model_dump(mode="json")` (user names already redacted for the
    viewer); `business` is `BusinessOut` as a dict. `copy` is the copy number (2, 3, …) for
    reprints, None for the original or a preview."""
    kind = kind_for(order)
    colors = []
    for color_summary in order["summary"]["colors"]:
        color = color_summary["color"]
        boxes = [
            {
                "position": box["position"],
                "lines": [_line(line, line.get("count"), line.get("kg")) for line in box["lines"]],
            }
            for box in order["boxes"]
            if box["color"] == color
        ]
        colors.append(
            {
                "color": color,
                "label_km": COLOR_SECTIONS[color][0],
                "label_en": COLOR_SECTIONS[color][1],
                "box_km": COLORS[color][0],
                "box_en": COLORS[color][1],
                "boxes": boxes,
                "box_count": color_summary["boxes"],
                "totals": _items(color_summary["items"]),
            }
        )
    returns = []
    for r in order.get("returns") or []:
        km, en = short_name(r)
        reviewed = r.get("reviewed_at") is not None
        returns.append(
            {
                "name_km": km,
                "name_en": en,
                "returned": quantity_text(r.get("returned_count"), r.get("returned_kg")),
                "to_stock": quantity_text(r.get("to_stock_count"), r.get("to_stock_kg"))
                if reviewed
                else None,
                "to_wasted": quantity_text(r.get("to_wasted_count"), r.get("to_wasted_kg"))
                if reviewed
                else None,
            }
        )
    customer = order["customer"]
    return {
        "kind": kind,
        "labels": LABELS,
        "sample": sample,
        "business": {
            "name_km": business["name_km"],
            "name_en": business["name_en"],
            "address_km": business.get("address_km"),
            "address_en": business.get("address_en"),
            "phone": business.get("phone_display"),
            "footer_note_km": business.get("footer_note_km"),
            "footer_note_en": business.get("footer_note_en"),
            "logo": _data_uri(*logo) if logo else None,
        },
        "order": {
            "code": order["code"],
            "status": order["status"],
            "status_km": STATUSES[order["status"]][0],
            "status_en": STATUSES[order["status"]][1],
            "cancelled": order["status"] == "cancelled",
            "cancel_reason": order.get("cancel_reason"),
            "customer": customer["name"],
            "customer_phone": customer.get("phone_display"),
            "customer_location": customer.get("location"),
            "delivery_date": _day(order["delivery_date"]),
            "driver": _name(order.get("driver")),
            "prepared_by": _name(order.get("created_by")),
            "note": order.get("note"),
            "return_reason": order.get("return_reason"),
        },
        "printed_at": printed_at.strftime("%d/%m/%Y %H:%M"),
        "copy": copy,
        "colors": colors,
        "total": {
            "boxes": order["summary"]["total"]["boxes"],
            "lines": _items(order["summary"]["total"]["items"]),
            # Prices later.
            "amount": order.get("total_amount"),
        },
        "returns": returns,
        "returns_reviewed": any(r["to_stock"] is not None for r in returns),
        "qr": _qr(app_url) if app_url else None,
    }


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _qr(url: str) -> str:
    import segno

    return segno.make(url, error="m").svg_data_uri(border=0, dark="#000", light=None)


def sample_order() -> dict[str, Any]:
    """A made-up order for the Business info preview (when there's no order to show)."""
    liver = byproduct_packed("liver")

    def item(code: str, count: int | None = None, kg: str | None = None) -> dict[str, Any]:
        km, en = _SHORT_NAMES.get(code, (code, code))
        return {"item_code": code, "name_km": km, "name_en": en, "count": count, "kg": kg}

    white = [item(PACKS_BIG, 10), item(PACKS_SMALL, 6)]
    black = [item(PACKS_BIG, 4), item(liver, kg="1.250")]
    return {
        "code": "OR-00000000-000",
        "status": "created",
        "customer": {
            "name": "Sample Shop",
            "phone_display": "012 345 678",
            "location": "Phnom Penh",
        },
        "delivery_date": date.today().isoformat(),
        "driver": {"full_name": "Driver name"},
        "created_by": {"full_name": "Your name"},
        "note": "Sample note",
        "return_reason": None,
        "cancel_reason": None,
        "boxes": [
            {"color": "white", "position": 1, "lines": white},
            {"color": "black", "position": 2, "lines": black},
        ],
        "summary": {
            "colors": [
                {"color": "white", "boxes": 1, "items": white},
                {"color": "black", "boxes": 1, "items": black},
            ],
            "total": {
                "boxes": 2,
                "items": [item(PACKS_BIG, 14), item(PACKS_SMALL, 6), item(liver, kg="1.250")],
            },
        },
        "returns": [],
    }
