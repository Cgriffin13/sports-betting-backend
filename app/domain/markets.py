from typing import Final

ALLOWED_MARKETS: Final = frozenset({"h2h", "spreads", "totals"})
DEFAULT_MARKETS: Final = ("h2h", "spreads", "totals")
MARKET_ALIASES: Final = {
    "ML": "h2h",
    "MONEYLINE": "h2h",
    "H2H": "h2h",
    "SPREAD": "spreads",
    "SPREADS": "spreads",
    "TOTAL": "totals",
    "TOTALS": "totals",
    "OU": "totals",
    "OVER_UNDER": "totals",
}


def normalize_markets(markets: list[str] | None) -> list[str]:
    if not markets:
        return list(DEFAULT_MARKETS)
    normalized = [
        MARKET_ALIASES.get((market or "").strip().upper(), (market or "").strip().lower())
        for market in markets
    ]
    supported = [market for market in normalized if market in ALLOWED_MARKETS]
    return supported or list(DEFAULT_MARKETS)
