from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MONEY_QUANTUM = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Convert a value to finite cents using round-half-up semantics."""
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Money value must be a finite number") from None
    if not amount.is_finite():
        raise ValueError("Money value must be a finite number")
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def money_json(value: Decimal) -> float:
    """Compatibility JSON representation; Decimal remains authoritative internally."""
    return float(money(value))
