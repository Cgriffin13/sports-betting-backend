from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.main import create_app
from app.persistence.market_repository import SqlAlchemyMarketDataRepository
from app.persistence.pricing_repository import SqlAlchemyPricingObservationRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import ProviderFetchResult
from app.providers.odds_api import TheOddsApiProvider
from app.schemas.opportunities import PricingAnalysisResponse
from app.security import ApiKeyAuthenticator
from app.services.pricing_service import PricingService, build_pricing_policy


class FixtureResponse:
    status_code = 200

    def __init__(self, payload: list[Any]) -> None:
        self._payload = payload
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[Any]:
        return self._payload


def load_payload() -> list[Any]:
    return json.loads((Path(__file__).parent / "fixtures" / "ncaaf_odds.json").read_text(encoding="utf-8"))


def parse_payload(payload: list[Any], *, league: str, requested_at: datetime) -> ProviderFetchResult:
    return TheOddsApiProvider(
        "fixture-key",
        requester=lambda url, *, params, timeout: FixtureResponse(payload),
        cache_ttl_seconds=0,
        clock=lambda: requested_at,
    ).fetch_current_odds(league, ["h2h", "spreads", "totals"])


def persist_payload(
    session_factory: sessionmaker[Session],
    payload: list[Any],
    *,
    league: str,
    requested_at: datetime,
) -> None:
    repository = SqlAlchemyMarketDataRepository(
        session_factory,
        freshness_seconds=20_000,
        clock=lambda: requested_at,
    )
    repository.persist_fetch(parse_payload(payload, league=league, requested_at=requested_at))


def pricing_service(session_factory: sessionmaker[Session], *, minimum_books: int = 2) -> PricingService:
    return PricingService(
        SqlAlchemyPricingObservationRepository(session_factory),
        build_pricing_policy(
            minimum_books=minimum_books,
            minimum_ev=Decimal("0.01"),
            minimum_probability_edge=Decimal("0.005"),
            outlier_threshold=Decimal("0.03"),
            maximum_dispersion=Decimal("0.08"),
            supported_books=("draftkings", "fanduel", "betmgm"),
        ),
    )


def make_moneyline_opportunity(payload: list[Any]) -> None:
    for book in payload[0]["bookmakers"]:
        outcomes = book["markets"][0]["outcomes"]
        outcomes[0]["price"] = -110
        outcomes[1]["price"] = -110
    betmgm = payload[0]["bookmakers"][2]["markets"][0]["outcomes"]
    betmgm[0]["price"] = 110
    betmgm[1]["price"] = -130


def test_sql_repository_and_service_replay_stored_ncaaf_with_full_provenance(
    session_factory: sessionmaker[Session],
) -> None:
    payload = load_payload()
    make_moneyline_opportunity(payload)
    persist_payload(
        session_factory,
        payload,
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 20, 0, 30, tzinfo=UTC),
    )

    result = pricing_service(session_factory).analyze(
        leagues=["CFB"],
        market_types=["moneyline", "spread", "total"],
        as_of=datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
        event_date=datetime(2026, 8, 29, tzinfo=UTC).date(),
        top_n=10,
    )

    assert len(result.opportunities) == 1
    opportunity = result.opportunities[0]
    assert opportunity.league == "NCAAF"
    assert opportunity.market_type == "moneyline"
    assert opportunity.selection_side == "home"
    assert opportunity.best_sportsbook_key == "betmgm"
    assert opportunity.best_american_odds == 110
    assert opportunity.final_fair_probability_source == "market_consensus"
    assert opportunity.proprietary_model_probability is None
    assert opportunity.books_contributing == 3
    assert len(opportunity.source_observation_ids) == 6
    assert len(opportunity.snapshot_ids) == 1
    assert len(opportunity.book_probabilities) == 3


def test_realistic_ncaaf_fixture_prices_moneyline_spread_and_total_exactly(
    session_factory: sessionmaker[Session],
) -> None:
    persist_payload(
        session_factory,
        load_payload(),
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 20, 0, 30, tzinfo=UTC),
    )
    service = PricingService(
        SqlAlchemyPricingObservationRepository(session_factory),
        build_pricing_policy(
            minimum_books=2,
            minimum_ev=Decimal("-1"),
            minimum_probability_edge=Decimal("-1"),
            outlier_threshold=Decimal("0.03"),
            maximum_dispersion=Decimal("0.08"),
            supported_books=("draftkings", "fanduel", "betmgm"),
        ),
    )

    result = service.analyze(
        leagues=["NCAAF"],
        market_types=["moneyline", "spread", "total"],
        as_of=datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
        event_date=datetime(2026, 8, 29, tzinfo=UTC).date(),
        top_n=10,
    )

    selected = {(item.market_type, item.selection_side, item.point): item for item in result.opportunities}
    moneyline = selected[("moneyline", "home", None)]
    spread = selected[("spread", "home", Decimal("-3.500"))]
    total = selected[("total", "over", Decimal("52.500"))]
    assert moneyline.no_vig_consensus_probability == Decimal("0.588211546225")
    assert moneyline.best_sportsbook_key == "betmgm"
    assert moneyline.best_american_odds == -150
    assert moneyline.ev_per_unit == Decimal("-0.0196474229583333333333333331")
    assert spread.no_vig_consensus_probability == Decimal("0.5029839670475148483901219131")
    assert spread.best_sportsbook_key == "draftkings"
    assert spread.best_american_odds == -110
    assert spread.ev_per_unit == Decimal("-0.0397578810911080167097672569")
    assert spread.consensus_fair_point == Decimal("-3.588530577")
    assert total.no_vig_consensus_probability == Decimal("0.5075592296317411402157164869")
    assert total.best_sportsbook_key == "draftkings"
    assert total.best_american_odds == -108
    assert total.ev_per_unit == Decimal("-0.0224785207092392855104719511")
    assert total.consensus_fair_point == Decimal("52.659172943")


def test_replay_repository_prevents_future_snapshot_leakage_and_replaces_moved_line(
    session_factory: sessionmaker[Session],
) -> None:
    first = load_payload()
    for book in first[0]["bookmakers"]:
        book["last_update"] = "2026-08-29T10:00:00Z"
        for market in book["markets"]:
            market["last_update"] = "2026-08-29T10:00:00Z"
    first[0]["bookmakers"][1]["markets"][1]["outcomes"][0]["point"] = -3.5
    first[0]["bookmakers"][1]["markets"][1]["outcomes"][1]["point"] = 3.5
    persist_payload(
        session_factory,
        first,
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 10, 0, 5, tzinfo=UTC),
    )

    moved = copy.deepcopy(first)
    draftkings_spread = moved[0]["bookmakers"][0]["markets"][1]
    draftkings_spread["last_update"] = "2026-08-29T13:00:00Z"
    draftkings_spread["outcomes"][0]["point"] = -4.5
    draftkings_spread["outcomes"][1]["point"] = 4.5
    betmgm_spread = moved[0]["bookmakers"][2]["markets"][1]
    betmgm_spread["last_update"] = "2026-08-29T13:00:00Z"
    betmgm_spread["outcomes"][0]["point"] = -4.5
    betmgm_spread["outcomes"][1]["point"] = 4.5
    persist_payload(
        session_factory,
        moved,
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 13, 0, 5, tzinfo=UTC),
    )

    service = PricingService(
        SqlAlchemyPricingObservationRepository(session_factory),
        build_pricing_policy(
            minimum_books=2,
            minimum_ev=Decimal("-1"),
            minimum_probability_edge=Decimal("-1"),
            outlier_threshold=Decimal("0.03"),
            maximum_dispersion=Decimal("0.08"),
            supported_books=("draftkings", "fanduel", "betmgm"),
        ),
    )
    at_eleven = service.analyze(
        leagues=["NCAAF"],
        market_types=["spread"],
        as_of=datetime(2026, 8, 29, 11, 0, tzinfo=UTC),
        event_date=datetime(2026, 8, 29, tzinfo=UTC).date(),
        top_n=10,
    )
    at_fourteen = service.analyze(
        leagues=["NCAAF"],
        market_types=["spread"],
        as_of=datetime(2026, 8, 29, 14, 0, tzinfo=UTC),
        event_date=datetime(2026, 8, 29, tzinfo=UTC).date(),
        top_n=10,
    )

    assert {item.point for item in at_eleven.opportunities} == {Decimal("-3.5"), Decimal("3.5")}
    # The 13:00 snapshot is selected exclusively, while the cross-line engine
    # correctly keeps FanDuel's better executable -3.5 home-side alternative.
    assert {item.point for item in at_fourteen.opportunities} == {Decimal("-3.5"), Decimal("4.5")}
    assert not set(at_eleven.opportunities[0].snapshot_ids) & set(at_fourteen.opportunities[0].snapshot_ids)


def test_pricing_query_keeps_ncaaf_distinct_from_ncaab(session_factory: sessionmaker[Session]) -> None:
    ncaaf = load_payload()
    make_moneyline_opportunity(ncaaf)
    persist_payload(
        session_factory,
        ncaaf,
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 20, 0, 30, tzinfo=UTC),
    )
    ncaab = copy.deepcopy(ncaaf)
    ncaab[0].update(
        {
            "id": "ncaab-2026-001",
            "sport_key": "basketball_ncaab",
            "sport_title": "NCAAB",
            "home_team": "Basketball Home",
            "away_team": "Basketball Away",
        }
    )
    for book in ncaab[0]["bookmakers"]:
        for market in book["markets"]:
            for outcome in market["outcomes"]:
                if outcome["name"] == "Coastal Tech":
                    outcome["name"] = "Basketball Home"
                elif outcome["name"] == "Mountain State":
                    outcome["name"] = "Basketball Away"
    persist_payload(
        session_factory,
        ncaab,
        league="NCAAB",
        requested_at=datetime(2026, 8, 29, 20, 0, 31, tzinfo=UTC),
    )

    result = pricing_service(session_factory).analyze(
        leagues=["NCAAF"],
        market_types=["moneyline"],
        as_of=datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
        event_date=datetime(2026, 8, 29, tzinfo=UTC).date(),
        top_n=10,
    )

    assert {item.league for item in result.opportunities} == {"NCAAF"}
    assert {item.home_team for item in result.opportunities} == {"Coastal Tech"}


def test_opportunities_endpoint_is_authenticated_transparent_and_backward_compatible(
    session_factory: sessionmaker[Session],
    settings: Settings,
    repository: SqlAlchemyPortfolioRepository,
    authenticator: ApiKeyAuthenticator,
) -> None:
    payload = load_payload()
    make_moneyline_opportunity(payload)
    persist_payload(
        session_factory,
        payload,
        league="NCAAF",
        requested_at=datetime(2026, 8, 29, 20, 0, 30, tzinfo=UTC),
    )
    application = create_app(
        settings=settings,
        repository=repository,
        pricing_repository=SqlAlchemyPricingObservationRepository(session_factory),
        authenticator=authenticator,
        clock=lambda: datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
    )
    anonymous = TestClient(application)
    client = TestClient(application, headers={"X-API-Key": "test-primary-key"})

    assert anonymous.post("/opportunities", json={"leagues": ["NCAAF"]}).status_code == 401
    response = client.post(
        "/opportunities",
        json={
            "leagues": ["NCAAF"],
            "market_types": ["moneyline"],
            "event_date": "2026-08-29",
            "top_n": 10,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_type"] == "market_consensus_baseline"
    assert body["paper_research_only"] is True
    assert body["opportunities_returned"] == 1
    assert body["opportunities"][0]["proprietary_model_probability"] is None
    assert body["opportunities"][0]["final_fair_probability_source"] == "market_consensus"
    PricingAnalysisResponse.model_validate(body)


def test_opportunities_endpoint_accepts_zero_results_and_rejects_naive_cutoff(
    client: TestClient,
) -> None:
    zero = client.post("/opportunities", json={"leagues": ["NCAAF"], "top_n": 10})
    invalid = client.post(
        "/opportunities",
        json={"leagues": ["NCAAF"], "as_of": "2026-08-29T20:00:00"},
    )

    assert zero.status_code == 200
    assert zero.json()["opportunities"] == []
    assert zero.json()["opportunities_returned"] == 0
    assert invalid.status_code == 422


def test_replay_rejects_unknown_policy_versions(session_factory: sessionmaker[Session]) -> None:
    service = pricing_service(session_factory)

    with pytest.raises(ValueError, match="Unsupported pricing policy"):
        service.analyze(
            leagues=["NCAAF"],
            market_types=["moneyline"],
            as_of=datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
            event_date=None,
            top_n=10,
            pricing_policy_version="future-policy",
        )
    with pytest.raises(ValueError, match="Unsupported qualification policy"):
        service.analyze(
            leagues=["NCAAF"],
            market_types=["moneyline"],
            as_of=datetime(2026, 8, 29, 20, 1, tzinfo=UTC),
            event_date=None,
            top_n=10,
            qualification_policy_version="future-policy",
        )
