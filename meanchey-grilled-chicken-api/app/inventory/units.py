"""Quantity units of inventory items, one rule everywhere (mirrored by the UI's lib/quantity.ts):

| unit    | precision      | stored in                             |
|---------|----------------|---------------------------------------|
| `count` | whole number   | `count` / `count_delta`               |
| `kg`    | 3 decimals     | `kg` / `kg_delta` (NUMERIC(12,3))     |
| `g`     | 1 decimal      | `g` / `g_delta` (NUMERIC(14,1))       |
| `m2`    | 2 decimals     | `m2` / `m2_delta` (NUMERIC(14,2))     |

Production items keep their own columns (count and/or kg); materials have exactly one unit.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Unit = Literal["count", "kg", "g", "m2"]
UNITS: tuple[Unit, ...] = ("count", "kg", "g", "m2")
DECIMALS: dict[Unit, int] = {"count": 0, "kg": 3, "g": 1, "m2": 2}
# The same measure (weight): converting between them keeps the amount.
WEIGHT_UNITS: frozenset[Unit] = frozenset({"kg", "g"})
# Largest amount accepted in one add / remove (keeps NUMERIC columns safe).
MAX_QUANTITY: dict[Unit, Decimal] = {
    "count": Decimal(10_000_000),
    "kg": Decimal("999999.999"),
    "g": Decimal("99999999.9"),
    "m2": Decimal("999999999.99"),
}


def quantum(unit: Unit) -> Decimal:
    return Decimal(1).scaleb(-DECIMALS[unit])


def quantize(unit: Unit, value: Decimal) -> Decimal:
    """Round to the unit's precision (half up)."""
    return Decimal(value).quantize(quantum(unit), rounding=ROUND_HALF_UP)


def has_precision(unit: Unit, value: Decimal) -> bool:
    """True when `value` has no more decimals than the unit allows."""
    return Decimal(value) == quantize(unit, value)


def convert(value: Decimal, from_unit: Unit, to_unit: Unit) -> Decimal:
    """kg ↔ g (rounded to the target precision); same unit unchanged. Count and m² can't convert."""
    if from_unit == to_unit:
        return quantize(to_unit, value)
    if {from_unit, to_unit} != WEIGHT_UNITS:
        raise ValueError(f"can't convert {from_unit} to {to_unit}")
    factor = Decimal(1000) if from_unit == "kg" else Decimal("0.001")
    return quantize(to_unit, Decimal(value) * factor)


def same_measure(a: Unit, b: Unit) -> bool:
    return a == b or {a, b} == WEIGHT_UNITS
