from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final

CANONICAL_MARKET_TYPES: Final = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}
FULL_GAME_PERIOD: Final = "full_game"
FRESHNESS_POLICY_VERSION: Final = "market-freshness-v1"


def canonical_market_type(provider_market: str) -> str:
    try:
        return CANONICAL_MARKET_TYPES[provider_market]
    except KeyError:
        raise ValueError(f"Unsupported provider market '{provider_market}'") from None


def selection_side(
    market_type: str,
    selection: str,
    *,
    home_team: str,
    away_team: str,
) -> str:
    normalized = selection.strip().casefold()
    if market_type == "total":
        if normalized == "over":
            return "over"
        if normalized == "under":
            return "under"
        raise ValueError("Total selection must be Over or Under")
    if normalized == home_team.strip().casefold():
        return "home"
    if normalized == away_team.strip().casefold():
        return "away"
    if market_type == "moneyline" and normalized in {"draw", "tie"}:
        return "draw"
    raise ValueError("Selection does not match the event participants")


def exact_point(value: object, *, required: bool) -> Decimal | None:
    if value is None:
        if required:
            raise ValueError("Spread and total observations require an exact point")
        return None
    try:
        point = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Point must be finite") from None
    if not point.is_finite():
        raise ValueError("Point must be finite")
    return point.quantize(Decimal("0.001"))


def point_identity(point: Decimal | None) -> str:
    return "none" if point is None else format(point, ".3f")
