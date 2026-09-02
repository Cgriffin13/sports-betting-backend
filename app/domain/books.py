import re
from typing import Final

BOOK_ALIASES: Final = {
    "draftkings": ("draftkings", "DraftKings"),
    "draft kings": ("draftkings", "DraftKings"),
    "fanduel": ("fanduel", "FanDuel"),
    "fan duel": ("fanduel", "FanDuel"),
    "betmgm": ("betmgm", "BetMGM"),
    "bet mgm": ("betmgm", "BetMGM"),
    "betrivers": ("betrivers", "BetRivers"),
    "bet rivers": ("betrivers", "BetRivers"),
    "williamhill_us": ("williamhill_us", "Caesars"),
    "caesars": ("williamhill_us", "Caesars"),
    "caesars sportsbook": ("williamhill_us", "Caesars"),
    "fanatics": ("fanatics", "Fanatics"),
    "fanatics sportsbook": ("fanatics", "Fanatics"),
}


def normalize_book(provider_key: str | None, display_name: str | None) -> tuple[str, str]:
    candidate = (provider_key or display_name or "unknown").strip().lower()
    if candidate in BOOK_ALIASES:
        return BOOK_ALIASES[candidate]
    canonical_key = re.sub(r"[^a-z0-9]+", "_", candidate).strip("_") or "unknown"
    return canonical_key, (display_name or provider_key or "Unknown").strip()
