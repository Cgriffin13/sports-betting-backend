import re
from typing import Final

BOOK_ALIASES: Final = {
    "draftkings": ("draftkings", "DraftKings"),
    "fanduel": ("fanduel", "FanDuel"),
    "betmgm": ("betmgm", "BetMGM"),
}


def normalize_book(provider_key: str | None, display_name: str | None) -> tuple[str, str]:
    candidate = (provider_key or display_name or "unknown").strip().lower()
    if candidate in BOOK_ALIASES:
        return BOOK_ALIASES[candidate]
    canonical_key = re.sub(r"[^a-z0-9]+", "_", candidate).strip("_") or "unknown"
    return canonical_key, (display_name or provider_key or "Unknown").strip()
