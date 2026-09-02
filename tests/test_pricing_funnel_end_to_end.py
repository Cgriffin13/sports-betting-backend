from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.cli.verify_live_pricing import verify_fetch
from app.db.base import Base
from app.main import create_app
from app.providers.base import MarketGame, MarketOffer, ProviderFetchResult


NOW = datetime(2026, 9, 5, 13, 0, tzinfo=UTC)
KICKOFFS = (
    "2026-09-05T19:00:00Z",
    "2026-09-05T20:00:00Z",
    "2026-09-05T21:00:00Z",
    "2026-09-05T22:00:00Z",
    "2026-09-05T23:00:00Z",
    "2026-09-05T23:30:00Z",
    "2026-09-05T23:50:00Z",
)


class CountingProvider:
    configured = True

    def __init__(self, fetch: ProviderFetchResult) -> None:
        self.fetch = fetch
        self.calls: list[tuple[str, list[str]]] = []

    def fetch_current_odds(self, sport: str, markets: list[str]) -> ProviderFetchResult:
        self.calls.append((sport, markets))
        return self.fetch


def _offer(
    book_key: str,
    market: str,
    selection: str,
    odds: int,
    *,
    point: Decimal | None = None,
) -> MarketOffer:
    titles = {
        "draftkings": "DraftKings",
        "fanduel": "FanDuel",
        "betmgm": "BetMGM",
        "williamhill_us": "Caesars Sportsbook",
        "bovada": "Bovada",
    }
    return MarketOffer(
        book=titles[book_key],
        book_key=book_key,
        market_type=market,
        selection=selection,
        odds=odds,
        point=point,
        has_point=point is not None,
        provider_updated_at=NOW - timedelta(minutes=5),
    )


def _game(
    number: int,
    home: str,
    away: str,
    offers: tuple[MarketOffer, ...],
) -> MarketGame:
    return MarketGame(
        provider_event_id=f"saturday-{number}",
        sport="NCAAF",
        home_team=home,
        away_team=away,
        commence_time=KICKOFFS[number - 1],
        offers=offers,
        status="scheduled",
        provider_updated_at=NOW,
    )


def _saturday_fetch() -> ProviderFetchResult:
    qualified = tuple(
        _offer(book, "h2h", selection, odds)
        for book, prices in {
            "draftkings": {"Qualified Home": 122, "Qualified Away": 100},
            "fanduel": {"Qualified Home": -110, "Qualified Away": -110},
            "betmgm": {"Qualified Home": -120, "Qualified Away": 100},
        }.items()
        for selection, odds in prices.items()
    )
    watchlist = tuple(
        _offer(book, "h2h", selection, odds)
        for book, prices in {
            "draftkings": {"Watch Home": 102, "Watch Away": 102},
            "fanduel": {"Watch Home": -110, "Watch Away": -110},
        }.items()
        for selection, odds in prices.items()
    )
    true_pass = tuple(
        _offer(book, "h2h", selection, -110)
        for book in ("draftkings", "williamhill_us")
        for selection in ("Pass Home", "Pass Away")
    )
    unsupported = tuple(
        _offer("bovada", "h2h", selection, -110)
        for selection in ("Pass Home", "Pass Away")
    )
    fragmented_spread = tuple(
        _offer(book, "spreads", selection, -110, point=point)
        for book, home_point in (
            ("draftkings", Decimal("-17")),
            ("fanduel", Decimal("-17.5")),
            ("betmgm", Decimal("-18")),
        )
        for selection, point in (
            ("Fragment Home", home_point),
            ("Fragment Away", -home_point),
        )
    )
    integer_spread = tuple(
        _offer(book, "spreads", selection, -110, point=point)
        for book in ("draftkings", "fanduel")
        for selection, point in (
            ("Integer Home", Decimal("-3")),
            ("Integer Away", Decimal("3")),
        )
    )
    half_total = tuple(
        _offer(book, "totals", selection, -110, point=Decimal("51.5"))
        for book in ("draftkings", "fanduel")
        for selection in ("Over", "Under")
    )
    fragmented_total = tuple(
        _offer(book, "totals", selection, -110, point=point)
        for book, point in (
            ("draftkings", Decimal("51")),
            ("fanduel", Decimal("51.5")),
            ("betmgm", Decimal("52")),
        )
        for selection in ("Over", "Under")
    )
    games = (
        _game(1, "Qualified Home", "Qualified Away", qualified),
        _game(2, "Watch Home", "Watch Away", watchlist),
        _game(3, "Pass Home", "Pass Away", (*true_pass, *unsupported)),
        _game(4, "Fragment Home", "Fragment Away", fragmented_spread),
        _game(5, "Integer Home", "Integer Away", integer_spread),
        _game(6, "Half Total Home", "Half Total Away", half_total),
        _game(7, "Total Fragment Home", "Total Fragment Away", fragmented_total),
    )
    return ProviderFetchResult(
        provider_name="the_odds_api",
        provider_sport_key="americanfootball_ncaaf",
        canonical_league="NCAAF",
        requested_at=NOW,
        provider_retrieved_at=NOW,
        request_parameters={"markets": ["h2h", "spreads", "totals"]},
        raw_payload=[],
        response_metadata={"requests_remaining": 999},
        warnings=(),
        games=games,
    )


@pytest.fixture
def saturday_client(tmp_path: Path) -> tuple[TestClient, CountingProvider]:
    database = tmp_path / "saturday.sqlite3"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database.as_posix()}",
        app_api_key="saturday-test-key",
        starting_bankroll=Decimal("200"),
        data_dir=tmp_path,
    )
    provider = CountingProvider(_saturday_fetch())
    application = create_app(settings=settings, provider=provider, clock=lambda: NOW)
    Base.metadata.create_all(application.state.database_engine)
    return TestClient(application, headers={"X-API-Key": "saturday-test-key"}), provider


def test_realistic_saturday_slate_reaches_dashboard_with_auditable_funnel(
    saturday_client: tuple[TestClient, CountingProvider],
) -> None:
    client, provider = saturday_client
    with client:
        refresh = client.post("/dashboard/portfolio/paper-main/refresh-markets")
        recommendations = client.get("/portfolio/paper-main/recommendations?upcoming_only=true")
        watchlist = client.get("/portfolio/paper-main/watchlist?upcoming_only=true")
        system = client.get("/dashboard/system")

    assert refresh.status_code == 200, refresh.text
    assert recommendations.status_code == 200, recommendations.text
    assert watchlist.status_code == 200, watchlist.text
    assert system.status_code == 200, system.text
    assert provider.calls == [("NCAAF", ["h2h", "spreads", "totals"])]
    actionable = recommendations.json()["recommendations"]
    assert len(actionable) == 1
    qualified = actionable[0]
    assert qualified["home_team"] == "Qualified Home"
    assert qualified["sportsbook"] == "draftkings"
    assert Decimal(str(qualified["fair_probability"])) == Decimal("0.5")
    assert Decimal(str(qualified["implied_probability"])) == pytest.approx(
        Decimal(100) / Decimal(222), abs=Decimal("0.0000000001")
    )
    assert Decimal(str(qualified["edge"])) == pytest.approx(
        Decimal("0.5") - Decimal(100) / Decimal(222), abs=Decimal("0.0000000001")
    )
    assert Decimal(str(qualified["ev_per_unit"])) == Decimal("0.11")
    assert Decimal(qualified["stake"]) > 0

    research = watchlist.json()
    assert research["watchlist_count"] == 2
    assert {item["home_team"] for item in research["items"]} == {"Watch Home"}
    assert all("stake" not in item and item["actionable"] is False for item in research["items"])

    funnel = research["pricing_funnel"]
    assert funnel == {
        "games_received": 7,
        "games_analyzed": 7,
        "observations_received": 36,
        "observations_considered": 36,
        "latest_observations": 36,
        "supported_book_observations": 34,
        "unsupported_book_observations": 2,
        "supported_books_seen": 4,
        "unsupported_books_seen": 1,
        "snapshot_age_seconds": 0,
        "provider_quote_age_min_seconds": 300,
        "provider_quote_age_median_seconds": 300,
        "provider_quote_age_p90_seconds": 300,
        "provider_quote_age_max_seconds": 300,
        "eligible_observations": 34,
        "exact_paired_book_markets": 17,
        "comparable_market_groups": 7,
        "calculable_candidate_sides": 14,
        "positive_edge_candidates": 3,
        "positive_ev_candidates": 3,
        "pricing_qualified_candidates": 1,
        "watchlist_candidates": 2,
        "qualified_candidates": 1,
        "actionable_candidates": 1,
        "pass_candidates": 11,
    }
    assert "insufficient_books" not in research["rejection_counts"]
    assert "push_probability_not_modeled" not in research["rejection_counts"]
    assert research["rejection_counts"]["below_minimum_ev"] >= 2
    assert research["rejection_counts"]["below_minimum_edge"] >= 2
    assert research["rejection_counts"]["unsupported_or_inactive_book"] == 2
    assert research["pricing_pipeline_status"] == "HEALTHY"
    assert len(research["slates"]) == 1
    assert research["slates"][0]["weekday"] == "Saturday"
    assert research["slates"][0]["pricing_funnel"]["watchlist_candidates"] == 2

    watchlist_id = research["items"][0]["watchlist_id"]
    with client:
        approval = client.post(f"/recommendations/{watchlist_id}/approve")
    assert approval.status_code == 404
    assert refresh.json()["decisions"][0]["parlay_status"] == "PASS"
    assert provider.calls == [("NCAAF", ["h2h", "spreads", "totals"])]


def test_isolated_live_verification_contract_uses_the_same_healthy_pipeline(tmp_path: Path) -> None:
    report = verify_fetch(
        _saturday_fetch(),
        Settings(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'source.sqlite3').as_posix()}",
            app_api_key="verification-source-key",
            data_dir=tmp_path,
        ),
    )

    assert report["acceptance_passed"] is True
    assert report["integrity_status"] == "HEALTHY WITH QUALIFIED"
    assert report["provider_calls"] == 1
    assert report["ledger_or_bet_mutation"] is False
    assert report["pricing_funnel"]["eligible_observations"] == 34
    assert report["pricing_funnel"]["exact_paired_book_markets"] == 17
    assert report["pricing_funnel"]["calculable_candidate_sides"] == 14
    assert report["saturday_games_received"] == 7
    assert report["saturday"]["slate_date_utc"] == "2026-09-05"
    assert report["saturday"]["games"] == 7
    assert report["saturday"]["qualified_candidates"] == 1
