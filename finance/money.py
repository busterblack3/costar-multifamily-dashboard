"""Money helpers. All amounts are stored internally as integer cents."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional


def to_cents(amount) -> int:
    """Convert a SimpleFIN decimal string (or number) to integer cents.

    Negative amounts are outflows (spending); positive are inflows (income).
    """
    if amount is None or amount == "":
        return 0
    if isinstance(amount, int):
        return amount * 100
    try:
        d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return 0
    return int(d * 100)


def dollars(cents: Optional[int]) -> str:
    """Format integer cents as a signed dollar string, e.g. -1234 -> '-$12.34'."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    whole = abs(cents) // 100
    frac = abs(cents) % 100
    return f"{sign}${whole:,}.{frac:02d}"


def plain(cents: Optional[int]) -> str:
    """Format integer cents as an unsigned dollar string, e.g. -1234 -> '$12.34'."""
    if cents is None:
        return "—"
    whole = abs(cents) // 100
    frac = abs(cents) % 100
    return f"${whole:,}.{frac:02d}"
