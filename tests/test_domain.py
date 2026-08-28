import pytest

from app.domain.markets import normalize_markets
from app.domain.sports import normalize_sport
from app.providers.odds_api import SPORT_PROVIDER_KEYS
from app.time import commence_date_utc


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NCAAF", "NCAAF"),
        ("cfb", "NCAAF"),
        ("college_football", "NCAAF"),
        ("College Football", "NCAAF"),
        ("ncaab", "NCAAB"),
        ("college_basketball", "NCAAB"),
        ("nba", "NBA"),
        ("college", "COLLEGE"),
    ],
)
def test_sport_normalization(raw: str, expected: str) -> None:
    assert normalize_sport(raw) == expected


def test_ncaaf_provider_mapping_is_distinct_from_ncaab() -> None:
    assert SPORT_PROVIDER_KEYS["NCAAF"] == "americanfootball_ncaaf"
    assert SPORT_PROVIDER_KEYS["NCAAB"] == "basketball_ncaab"
    assert SPORT_PROVIDER_KEYS["NCAAF"] != SPORT_PROVIDER_KEYS["NCAAB"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ["h2h", "spreads", "totals"]),
        (["ML", "spread", "OU"], ["h2h", "spreads", "totals"]),
        (["h2h", "player_props"], ["h2h"]),
        (["player_props"], ["h2h", "spreads", "totals"]),
    ],
)
def test_market_normalization(raw: list[str] | None, expected: list[str]) -> None:
    assert normalize_markets(raw) == expected


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-08-28T18:30:00-07:00", "2026-08-29"),
        ("2026-08-29T01:30:00Z", "2026-08-29"),
        ("2026-08-29T01:30:00", None),
        ("not-a-date", None),
        (None, None),
    ],
)
def test_utc_date_normalization(timestamp: object, expected: str | None) -> None:
    result = commence_date_utc(timestamp)
    assert (str(result) if result else None) == expected
