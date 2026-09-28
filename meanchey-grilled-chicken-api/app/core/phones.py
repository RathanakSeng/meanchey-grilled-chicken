"""Phone number normalization (storage) and formatting (display).

Stored form: digits only, with an optional leading `+`, e.g. `012345678` or `+85512345678`.
Numbers are not converted between local and international form, so `012 345 678` and
`+855 12 345 678` are different stored values.
"""

import re

from app.core.errors import AppError, ErrorCode

PHONE_MIN_DIGITS = 8
PHONE_MAX_DIGITS = 15

# Separators people type: spaces (any whitespace), dashes, dots and parentheses.
_SEPARATORS = re.compile(r"[\s\-.()]+")
_NORMALIZED = re.compile(rf"\+?\d{{{PHONE_MIN_DIGITS},{PHONE_MAX_DIGITS}}}")

_CAMBODIA = "+855"


def _invalid() -> AppError:
    return AppError(
        422,
        ErrorCode.INVALID_PHONE,
        f"Phone must have {PHONE_MIN_DIGITS}-{PHONE_MAX_DIGITS} digits, optionally starting with +",
        {"min_digits": PHONE_MIN_DIGITS, "max_digits": PHONE_MAX_DIGITS},
    )


def normalize_phone(value: str | None) -> str | None:
    """Strip separators; keep an optional leading `+`. Empty means "no phone".

    Raises `INVALID_PHONE` unless the result is 8-15 digits.
    """
    if value is None:
        return None
    compact = _SEPARATORS.sub("", value)
    if not compact:
        return None
    if not _NORMALIZED.fullmatch(compact):
        raise _invalid()
    return compact


def _group_local(digits: str) -> str:
    """Cambodian subscriber layout: 2-3 digit prefix, then 3 + 3 or 3 + 4."""
    head = 3 if digits.startswith("0") else 2
    prefix, rest = digits[:head], digits[head:]
    if len(rest) <= 3:
        return f"{prefix} {rest}".strip()
    return f"{prefix} {rest[:3]} {rest[3:]}"


def format_phone(value: str | None) -> str | None:
    """Readable form of a stored phone: `012 345 678`, `+855 12 345 678`, `+66 812 345 678`."""
    if not value:
        return None
    if value.startswith(_CAMBODIA):
        return f"{_CAMBODIA} {_group_local(value[len(_CAMBODIA) :])}"
    if value.startswith("+"):
        # Unknown country code length: show it as a whole and group the rest in threes.
        digits = value[1:]
        cc, rest = digits[:2], digits[2:]
        groups = [rest[i : i + 3] for i in range(0, len(rest), 3)]
        if len(groups) > 1 and len(groups[-1]) == 1:
            groups[-2:] = [groups[-2] + groups[-1]]
        return " ".join([f"+{cc}", *groups])
    return _group_local(value)
