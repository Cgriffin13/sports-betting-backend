from typing import Final

SUPPORTED_SPORTS: Final = frozenset({"NCAAF", "NFL", "NCAAB", "NBA", "NHL", "MLB", "WNBA"})

SPORT_ALIASES: Final = {
    "NCAAF": "NCAAF",
    "CFB": "NCAAF",
    "COLLEGE_FOOTBALL": "NCAAF",
    "COLLEGE FOOTBALL": "NCAAF",
    "NFL": "NFL",
    "NCAAB": "NCAAB",
    "NCAAM": "NCAAB",
    "NCAA": "NCAAB",
    "NCAA_M": "NCAAB",
    "NCCAMB": "NCAAB",
    "COLLEGE_BASKETBALL": "NCAAB",
    "COLLEGE_MENS_BASKETBALL": "NCAAB",
    "NBA": "NBA",
    "NHL": "NHL",
    "MLB": "MLB",
    "WNBA": "WNBA",
}

DEFAULT_SPORTS: Final = ("NCAAF", "NFL", "NBA", "NCAAB", "MLB", "NHL", "WNBA")


def normalize_sport(value: str) -> str:
    normalized = (value or "").strip().upper()
    return SPORT_ALIASES.get(normalized, normalized)
