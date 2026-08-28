from datetime import date

from app.providers.base import MarketDataProviderError, MarketGame, MarketOffer
from app.services.odds_service import OddsService
from tests.conftest import FakeProvider


def sample_games() -> list[MarketGame]:
    return [
        MarketGame(
            provider_event_id="utc-date",
            sport="NCAAF",
            home_team="Home State",
            away_team="Away State",
            commence_time="2026-08-28T18:30:00-07:00",
            offers=(
                MarketOffer("DraftKings", "h2h", "Home State", -120),
                MarketOffer("DraftKings", "spreads", "Home State", -110, -3.5, True),
                MarketOffer("Caesars", "h2h", "Home State", -115),
            ),
        ),
        MarketGame("next-date", "NCAAF", "Later Home", "Later Away", "2026-08-30T01:00:00Z", ()),
        MarketGame("naive", "NCAAF", "Unknown Home", "Unknown Away", "2026-08-29T12:00:00", ()),
    ]


def test_odds_service_normalizes_filters_and_serializes() -> None:
    provider = FakeProvider(sample_games(), configured=True)
    result = OddsService(provider).get_odds(
        requested_date=date(2026, 8, 29),
        sports=["CFB"],
        markets=["h2h", "spreads", "player_props"],
        allowed_books=None,
        max_games_per_sport=50,
    )

    assert result["sports"] == ["NCAAF"]
    assert result["markets"] == ["h2h", "spreads"]
    assert [game["game_id"] for game in result["games"]] == ["utc-date"]
    assert {offer["book"] for offer in result["games"][0]["offers"]} == {"DraftKings"}
    assert any(offer.get("point") == -3.5 for offer in result["games"][0]["offers"])
    assert provider.calls == [("NCAAF", ["h2h", "spreads"])]


def test_odds_service_returns_sanitized_provider_error() -> None:
    provider = FakeProvider(configured=True, error=MarketDataProviderError("Provider request failed"))
    result = OddsService(provider).get_odds(
        requested_date=date(2026, 8, 29),
        sports=["NCAAF"],
        markets=None,
        allowed_books=None,
        max_games_per_sport=50,
    )
    assert result["errors"] == [{"sport": "NCAAF", "error": "Provider request failed"}]


def test_odds_service_preserves_missing_key_contract() -> None:
    result = OddsService(FakeProvider()).get_odds(
        requested_date=date(2026, 8, 29),
        sports=None,
        markets=None,
        allowed_books=None,
        max_games_per_sport=50,
    )
    assert result == {
        "error": "Missing ODDS_API_KEY in server environment.",
        "date": "2026-08-29",
        "date_timezone": "UTC",
        "games": [],
    }


def test_odds_service_reports_unsupported_sport_without_provider_call() -> None:
    provider = FakeProvider(configured=True)
    result = OddsService(provider).get_odds(
        requested_date=date(2026, 8, 29),
        sports=["college"],
        markets=None,
        allowed_books=None,
        max_games_per_sport=50,
    )
    assert result["errors"] == [{"sport": "COLLEGE", "error": "Unsupported sport 'COLLEGE'"}]
    assert provider.calls == []
