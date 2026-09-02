from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.base import Base
from app.domain.portfolio_engine import fractional_kelly_with_push
from app.main import create_app
from app.providers.odds_api import TheOddsApiProvider


NOW = datetime(2026, 9, 5, 13, 0, tzinfo=UTC)
UPDATED_AT = "2026-09-05T12:59:30Z"


class FakeResponse:
    status_code = 200
    headers = {
        "Date": "Sat, 05 Sep 2026 13:00:00 GMT",
        "x-requests-remaining": "999",
    }

    def __init__(self, payload: list[dict[str, Any]]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return self._payload


def _book(key: str, markets: list[dict[str, Any]]) -> dict[str, Any]:
    titles = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM"}
    return {"key": key, "title": titles[key], "last_update": UPDATED_AT, "markets": markets}


def _market(key: str, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"key": key, "last_update": UPDATED_AT, "outcomes": outcomes}


def _event(
    event_id: str,
    home: str,
    away: str,
    kickoff: str,
    market_key: str,
    prices: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "id": event_id,
        "sport_key": "americanfootball_ncaaf",
        "commence_time": kickoff,
        "home_team": home,
        "away_team": away,
        "bookmakers": [_book(key, [_market(market_key, outcomes)]) for key, outcomes in prices.items()],
    }


def _payload() -> list[dict[str, Any]]:
    # The crossed prices are intentional executable-price dislocations. The other
    # two books keep the no-vig consensus distinct from the best offered price.
    spread = {
        "draftkings": [
            {"name": "Spread Home", "price": -110, "point": -3.5},
            {"name": "Spread Away", "price": 120, "point": 3.5},
        ],
        "fanduel": [
            {"name": "Spread Home", "price": -135, "point": -3.5},
            {"name": "Spread Away", "price": 115, "point": 3.5},
        ],
        "betmgm": [
            {"name": "Spread Home", "price": -140, "point": -3.5},
            {"name": "Spread Away", "price": 120, "point": 3.5},
        ],
    }
    total = {
        "draftkings": [
            {"name": "Over", "price": -110, "point": 52.5},
            {"name": "Under", "price": 120, "point": 52.5},
        ],
        "fanduel": [
            {"name": "Over", "price": -135, "point": 52.5},
            {"name": "Under", "price": 115, "point": 52.5},
        ],
        "betmgm": [
            {"name": "Over", "price": -140, "point": 52.5},
            {"name": "Under", "price": 120, "point": 52.5},
        ],
    }
    moderate_moneyline = {
        "draftkings": [
            {"name": "Moderate Home", "price": 100},
            {"name": "Moderate Away", "price": 100},
        ],
        "fanduel": [
            {"name": "Moderate Home", "price": -135},
            {"name": "Moderate Away", "price": 115},
        ],
        "betmgm": [
            {"name": "Moderate Home", "price": -130},
            {"name": "Moderate Away", "price": 110},
        ],
    }
    longshot = {
        "draftkings": [
            {"name": "Longshot Home", "price": 1000},
            {"name": "Longshot Away", "price": -1100},
        ],
        "fanduel": [
            {"name": "Longshot Home", "price": 900},
            {"name": "Longshot Away", "price": -1100},
        ],
        "betmgm": [
            {"name": "Longshot Home", "price": 800},
            {"name": "Longshot Away", "price": -1200},
        ],
    }
    return [
        _event("spread-game", "Spread Home", "Spread Away", "2026-09-05T19:00:00Z", "spreads", spread),
        _event("total-game", "Total Home", "Total Away", "2026-09-05T20:00:00Z", "totals", total),
        _event(
            "moderate-ml-game",
            "Moderate Home",
            "Moderate Away",
            "2026-09-05T21:00:00Z",
            "h2h",
            moderate_moneyline,
        ),
        _event(
            "longshot-game",
            "Longshot Home",
            "Longshot Away",
            "2026-09-05T22:00:00Z",
            "h2h",
            longshot,
        ),
    ]


def test_moderate_odds_markets_survive_the_complete_today_path(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(_payload())

    database = tmp_path / "moderate-odds.sqlite3"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{database.as_posix()}",
        app_api_key="moderate-odds-test-key",
        odds_api_key="non-secret-fixture-key",
        starting_bankroll=Decimal("200"),
        data_dir=tmp_path,
    )
    provider = TheOddsApiProvider(
        settings.odds_api_key,
        requester=requester,
        clock=lambda: NOW,
        cache_ttl_seconds=0,
    )
    application = create_app(settings=settings, provider=provider, clock=lambda: NOW)
    Base.metadata.create_all(application.state.database_engine)
    client = TestClient(application, headers={"X-API-Key": settings.app_api_key})

    with client:
        refresh = client.post("/dashboard/portfolio/paper-main/refresh-markets")
        pricing = client.post(
            "/opportunities",
            json={
                "leagues": ["NCAAF"],
                "market_types": ["moneyline", "spread", "total"],
                "event_date": "2026-09-05",
                "as_of": NOW.isoformat(),
                "top_n": 10,
            },
        )
        today = client.get("/portfolio/paper-main/recommendations?upcoming_only=true")
        watchlist = client.get("/portfolio/paper-main/watchlist?upcoming_only=true")

    assert refresh.status_code == 200, refresh.text
    assert pricing.status_code == 200, pricing.text
    assert today.status_code == 200, today.text
    assert watchlist.status_code == 200, watchlist.text
    assert len(calls) == 1
    assert calls[0]["params"]["markets"] == "h2h,spreads,totals"

    recommendations = today.json()["recommendations"]
    assert [(item["market"], item["selection"], item["odds"]) for item in recommendations] == [
        ("spread", "Spread Home", -110),
        ("total", "Over", -110),
        ("moneyline", "Moderate Home", 100),
    ]
    assert all(Decimal(item["stake"]) >= Decimal("1.00") for item in recommendations)

    spread_item, total_item, moneyline_item = recommendations
    assert [item["portfolio_rank"] for item in recommendations] == [1, 2, 3]
    assert [item["classification"] for item in recommendations] == [
        "CORE",
        "CORE",
        "OPPORTUNISTIC",
    ]
    assert [Decimal(str(item["stake"])) for item in recommendations] == [
        Decimal("2.26"),
        Decimal("2.26"),
        Decimal("1.02"),
    ]
    assert Decimal(str(spread_item["point"])) == Decimal("-3.5")
    assert Decimal(str(total_item["point"])) == Decimal("52.5")
    assert Decimal(str(spread_item["fair_probability"])) > Decimal(str(spread_item["implied_probability"]))
    assert Decimal(str(total_item["fair_probability"])) > Decimal(str(total_item["implied_probability"]))
    assert Decimal(str(moneyline_item["fair_probability"])) > Decimal(
        str(moneyline_item["implied_probability"])
    )

    # The +1000 side is still calculated and has higher raw EV than either -110
    # candidate, but it cannot displace them on the actionable main board.
    pricing_items = pricing.json()["opportunities"]
    longshot_item = next(item for item in pricing_items if item["home_team"] == "Longshot Home")
    assert longshot_item["best_american_odds"] == 1000
    assert Decimal(str(longshot_item["ev_per_unit"])) > Decimal(str(spread_item["ev_per_unit"]))
    assert Decimal(str(longshot_item["ev_per_unit"])) > Decimal(str(total_item["ev_per_unit"]))
    longshot_raw_kelly = fractional_kelly_with_push(
        Decimal(str(longshot_item["final_fair_probability"])),
        Decimal(0),
        Decimal(str(longshot_item["best_decimal_odds"])),
    )
    assert Decimal(str(spread_item["adjusted_kelly_fraction"])) > longshot_raw_kelly
    assert Decimal(str(total_item["adjusted_kelly_fraction"])) > longshot_raw_kelly
    assert Decimal(str(spread_item["ranking_score"])) > Decimal(str(moneyline_item["ranking_score"]))
    assert Decimal(str(total_item["ranking_score"])) > Decimal(str(moneyline_item["ranking_score"]))
    analysis = today.json()["latest_decision"]["analysis_summary"]
    assert analysis["rejection_counts"]["outside_main_board_odds_profile"] == 1

    funnel = watchlist.json()["pricing_funnel"]
    assert funnel["games_received"] == 4
    assert funnel["exact_paired_book_markets"] == 12
    assert funnel["comparable_market_groups"] == 4
    assert funnel["calculable_candidate_sides"] == 8
    assert funnel["pricing_qualified_candidates"] == 4
    assert funnel["qualified_candidates"] == 3

    # GET /recommendations is the stored read used by Today. Matching the persisted
    # run proves no spread/total item vanished between ranking and the dashboard read.
    assert today.json()["latest_decision"]["decision_run_id"] == refresh.json()["decisions"][0][
        "decision_run_id"
    ]
    assert len({item["recommendation_id"] for item in recommendations}) == 3
