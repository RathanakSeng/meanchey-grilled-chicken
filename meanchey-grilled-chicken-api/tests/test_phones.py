import pytest

from app.core.errors import AppError
from app.core.phones import format_phone, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  - ", None),
        ("012 345 678", "012345678"),
        ("+855 12-345-678", "+85512345678"),
        ("(012).345.678", "012345678"),
        ("12345678", "12345678"),
        ("+123456789012345", "+123456789012345"),
    ],
)
def test_normalize(raw, expected) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["1234567", "1234567890123456", "+", "0 1 2 x", "855+12345678"])
def test_normalize_rejects(raw) -> None:
    with pytest.raises(AppError) as e:
        normalize_phone(raw)
    assert e.value.code == "INVALID_PHONE"


@pytest.mark.parametrize(
    ("stored", "display"),
    [
        (None, None),
        ("012345678", "012 345 678"),
        ("0123456789", "012 345 6789"),
        ("+85512345678", "+855 12 345 678"),
        ("+855123456789", "+855 12 345 6789"),
        ("12345678", "12 345 678"),
        ("+66812345678", "+66 812 345 678"),
        ("+6681234567", "+66 812 345 67"),
        ("+661234567", "+66 123 4567"),
    ],
)
def test_format(stored, display) -> None:
    assert format_phone(stored) == display
