from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.domain.portfolio_engine import ParlayPolicy, QualificationPolicy, RiskPolicy
from app.domain.pricing import PricingAnalysis
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.persistence.recommendation_repository import SqlAlchemyRecommendationRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.research.ncaaf.model_registry import registered_models
from app.services.recommendation_service import RecommendationService
from tests.conftest import FakeProvider
from tests.test_portfolio_engine import NOW, _opportunity
from tests.test_recommendation_persistence import _event


class StubPricingService:
    def __init__(self, opportunity: Any) -> None:
        self.opportunity = opportunity

    def analyze(self, **_: Any) -> PricingAnalysis:
        return PricingAnalysis(
            as_of=NOW,
            pricing_policy_version="market-baseline-v1",
            qualification_policy_version="baseline-qualification-v1",
            first_scheduled_start_utc=self.opportunity.scheduled_start_utc,
            candidates=(self.opportunity,),
            opportunities=(self.opportunity,),
            events_analyzed=1,
            observations_considered=6,
            paired_book_markets=3,
            opportunities_qualified=1,
            top_n_per_league=50,
            rejection_counts={},
            funnel={
                "games_received": 1,
                "games_analyzed": 1,
                "observations_received": 6,
                "observations_considered": 6,
                "latest_observations": 6,
                "eligible_observations": 6,
                "exact_paired_book_markets": 3,
                "comparable_market_groups": 1,
                "calculable_candidate_sides": 1,
                "positive_edge_candidates": 1,
                "positive_ev_candidates": 1,
                "pricing_qualified_candidates": 1,
            },
        )


def test_recommendation_api_is_approval_gated_and_authenticated(
    session_factory: sessionmaker[Session],
    settings: Any,
    authenticator: Any,
) -> None:
    from app.main import create_app

    portfolio_repository = SqlAlchemyPortfolioRepository(session_factory, Decimal("200"))
    app = create_app(
        settings=settings,
        provider=FakeProvider(),
        repository=portfolio_repository,
        authenticator=authenticator,
    )
    opportunity = _opportunity(odds=120, fair=Decimal("0.55"))
    _event(session_factory, opportunity.event_id, opportunity.home_team, opportunity.away_team)
    registry = SqlAlchemyModelRegistryRepository(session_factory)
    registry.register_models(registered_models())
    app.state.recommendation_service = RecommendationService(
        pricing_service=StubPricingService(opportunity),  # type: ignore[arg-type]
        registry_repository=registry,
        repository=SqlAlchemyRecommendationRepository(session_factory, Decimal("200")),
        qualification_policy=QualificationPolicy(),
        risk_policy=RiskPolicy(),
        parlay_policy=ParlayPolicy(),
    )
    client = TestClient(app)
    unauthorized = client.post(
        "/portfolio/main/recommendations/analyze",
        json={"slate_date": "2026-09-05", "as_of": NOW.isoformat()},
    )
    assert unauthorized.status_code == 401
    client.headers["X-API-Key"] = "test-primary-key"
    response = client.post(
        "/portfolio/main/recommendations/analyze",
        json={"slate_date": "2026-09-05", "as_of": NOW.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["straight_recommendations"]) == 1
    assert body["analysis_summary"]["games_analyzed"] == 1
    assert body["analysis_summary"]["pricing_funnel"]["qualified_candidates"] == 1
    assert body["watchlist_count"] == 0
    assert body["parlay_of_the_day"]["status"] == "PASS"
    recommendation_id = body["straight_recommendations"][0]["recommendation_id"]

    listing = client.get(
        "/portfolio/main/recommendations",
        params={"slate_date": date(2026, 9, 5).isoformat()},
    ).json()
    assert listing["recommendations"][0]["recommendation_id"] == recommendation_id
    assert listing["latest_decision"]["decision_run_id"] == body["decision_run_id"]
    assert listing["latest_decision"]["policy_versions"] == body["policy_versions"]

    watchlist = client.get("/portfolio/main/watchlist", params={"upcoming_only": True})
    assert watchlist.status_code == 200
    assert watchlist.json()["upcoming_games_analyzed"] == 1
    assert watchlist.json()["qualified_recommendations"] == 1
    assert watchlist.json()["items"] == []

    assert client.get("/portfolio/main").json()["bets"] == []
    approval = client.post(
        f"/recommendations/{recommendation_id}/approve",
        headers={"Idempotency-Key": "approve-1"},
    )
    assert approval.status_code == 200
    assert approval.json()["bankroll_after"] == 196.0
    assert len(client.get("/portfolio/main").json()["bets"]) == 1
    risk = client.get("/portfolio/main/risk", params={"slate_date": date(2026, 9, 5).isoformat()})
    assert risk.status_code == 200
    assert risk.json()["reserved_exposure"] == 4.0
    assert risk.json()["portfolio_state"] == "NORMAL"
    assert risk.json()["state_reason"] == "within_policy"
