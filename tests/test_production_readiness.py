from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import MarketSnapshot
from app.db.base import Base
from app.db.model_registry_models import ArtifactRegistryEntry, ModelRegistryEntry
from app.domain.identity import Principal
from app.domain.recommendation_timing import classify_recommendation_timing
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.providers.base import MarketGame, ProviderFetchResult
from app.services.dashboard_service import DashboardService
from app.services.market_ingestion_service import MarketIngestionResult
from app.services.market_refresh_service import (
    MarketRefreshInProgressError,
    MarketRefreshService,
    MarketRefreshUnavailableError,
)
from app.services.model_registry_bootstrap import bootstrap_ncaaf_registry
from app.persistence.dashboard_repository import SqlAlchemyDashboardRepository
from app.persistence.market_base import PersistedMarketSnapshot
from app.main import create_app
from app.config import Settings
from fastapi.testclient import TestClient
from decimal import Decimal


class StubOddsService:
    provider_configured = True

    def __init__(self, fetch: ProviderFetchResult, entered: Event | None = None, release: Event | None = None) -> None:
        self.fetch = fetch
        self.entered = entered
        self.release = release
        self.calls: list[tuple[str, list[str]]] = []

    def ingest_current(self, *, sport: str, markets: list[str]) -> MarketIngestionResult:
        self.calls.append((sport, markets))
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(timeout=3)
        return MarketIngestionResult(
            self.fetch,
            PersistedMarketSnapshot(uuid4(), 1, 18, ()),
        )


class StubRecommendationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def analyze(self, principal: Principal, **values: Any) -> dict[str, Any]:
        del principal
        self.calls.append(values)
        return {
            "decision_run_id": f"run-{values['slate_date']}",
            "straight_recommendations": [],
            "parlay_of_the_day": {"status": "PASS"},
            "pass_reasons": ["no_qualified_candidates"],
        }


def _fetch(requested_at: datetime) -> ProviderFetchResult:
    games = (
        MarketGame("event-1", "NCAAF", "Home", "Away", "2026-09-05T19:00:00Z", ()),
        MarketGame("event-2", "NCAAF", "Later", "Visitor", "2026-09-12T22:00:00Z", ()),
    )
    return ProviderFetchResult(
        provider_name="fake_provider",
        provider_sport_key="americanfootball_ncaaf",
        canonical_league="NCAAF",
        requested_at=requested_at,
        provider_retrieved_at=requested_at,
        request_parameters={"markets": ["h2h", "spreads", "totals"]},
        raw_payload=[],
        response_metadata={"requests_remaining": 100, "secret": "must-not-escape"},
        warnings=(),
        games=games,
    )


def test_registry_bootstrap_is_idempotent_and_complete(session_factory: sessionmaker[Session]) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    first_hash = bootstrap_ncaaf_registry(repository)
    second_hash = bootstrap_ncaaf_registry(repository)
    assert first_hash == second_hash
    with session_factory() as session:
        models = list(session.scalars(select(ModelRegistryEntry)))
        artifact_count = session.scalar(select(func.count()).select_from(ArtifactRegistryEntry)) or 0
        assert artifact_count >= 2
    assert len(models) == 7
    assert sum(item.status == "retained_benchmark" for item in models) == 4
    assert {item.status for item in models} >= {"retained_benchmark", "diagnostic", "rejected"}


def test_production_app_startup_bootstraps_registry(tmp_path: Any) -> None:
    database = tmp_path / "registry.sqlite3"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite+pysqlite:///{database.as_posix()}",
        app_api_key="bootstrap-test-key",
        starting_bankroll=Decimal("200"),
    )
    application = create_app(settings=settings, provider=StubProviderWithoutCalls())
    Base.metadata.create_all(application.state.database_engine)
    with TestClient(application, headers={"X-API-Key": "bootstrap-test-key"}) as client:
        response = client.get("/dashboard/system")
    assert response.status_code == 200
    assert len(response.json()["models"]) == 7
    assert response.json()["system_status"] == "OPERATIONAL"


def test_refresh_all_upcoming_slates_and_preserves_safe_metadata() -> None:
    odds = StubOddsService(_fetch(datetime(2026, 9, 5, 15, 0, tzinfo=UTC)))
    recommendations = StubRecommendationService()
    result = MarketRefreshService(odds, recommendations).refresh(
        Principal("owner", "Owner"), portfolio_id="paper-main"
    )
    assert odds.calls == [("NCAAF", ["h2h", "spreads", "totals"])]
    assert result["upcoming_events"] == 2
    assert len(result["decisions"]) == 2
    assert result["decisions"][0]["timing_classification"] == "EARLY_LOOKAHEAD"
    assert result["provider_metadata"] == {"requests_remaining": 100}
    assert {call["slate_date"].isoformat() for call in recommendations.calls} == {"2026-09-05", "2026-09-12"}


def test_refresh_rejects_concurrent_request() -> None:
    entered = Event()
    release = Event()
    service = MarketRefreshService(
        StubOddsService(_fetch(datetime(2026, 9, 5, 15, tzinfo=UTC)), entered, release),
        StubRecommendationService(),
    )
    worker = Thread(target=lambda: service.refresh(Principal("owner", "Owner"), portfolio_id="main"))
    worker.start()
    assert entered.wait(timeout=2)
    with pytest.raises(MarketRefreshInProgressError):
        service.refresh(Principal("owner", "Owner"), portfolio_id="main")
    release.set()
    worker.join(timeout=3)


def test_refresh_fails_cleanly_when_provider_is_not_configured() -> None:
    odds = StubOddsService(_fetch(datetime(2026, 9, 5, 15, tzinfo=UTC)))
    odds.provider_configured = False
    with pytest.raises(MarketRefreshUnavailableError, match="not configured"):
        MarketRefreshService(odds, StubRecommendationService()).refresh(
            Principal("owner", "Owner"), portfolio_id="paper-main"
        )


def test_refresh_endpoint_requires_authentication_and_returns_structured_result(raw_client: TestClient) -> None:
    service = MarketRefreshService(
        StubOddsService(_fetch(datetime(2026, 9, 5, 15, tzinfo=UTC))),
        StubRecommendationService(),
    )
    raw_client.app.state.market_refresh_service = service  # type: ignore[attr-defined]
    path = "/dashboard/portfolio/paper-main/refresh-markets"
    assert raw_client.post(path).status_code == 401
    response = raw_client.post(path, headers={"X-API-Key": "test-primary-key"})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["provider_metadata"] == {"requests_remaining": 100}
    unavailable_odds = StubOddsService(_fetch(datetime(2026, 9, 5, 15, tzinfo=UTC)))
    unavailable_odds.provider_configured = False
    raw_client.app.state.market_refresh_service = MarketRefreshService(  # type: ignore[attr-defined]
        unavailable_odds,
        StubRecommendationService(),
    )
    failed = raw_client.post(path, headers={"X-API-Key": "test-primary-key"})
    assert failed.status_code == 503
    assert failed.json()["detail"] == "The odds provider is not configured on the server"


def test_horizon_classification_distinguishes_lookahead_official_and_late() -> None:
    kickoff = datetime(2026, 9, 5, 19, tzinfo=UTC)
    assert classify_recommendation_timing(datetime(2026, 9, 5, 15, 0, tzinfo=UTC), kickoff)["timing_classification"] == "EARLY_LOOKAHEAD"
    assert classify_recommendation_timing(datetime(2026, 9, 5, 16, 10, tzinfo=UTC), kickoff)["timing_classification"] == "OFFICIAL_PRIMARY_HORIZON"
    assert classify_recommendation_timing(datetime(2026, 9, 5, 17, 0, tzinfo=UTC), kickoff)["timing_classification"] == "POST_HORIZON"


def test_stale_market_is_descriptive_not_global_system_degradation(
    session_factory: sessionmaker[Session],
    settings: Any,
) -> None:
    bootstrap_ncaaf_registry(SqlAlchemyModelRegistryRepository(session_factory))
    with session_factory.begin() as session:
        session.add(
            MarketSnapshot(
                id=uuid4(), provider_name="provider", provider_sport_key="americanfootball_ncaaf",
                canonical_league="NCAAF", requested_at=datetime(2026, 9, 1, tzinfo=UTC),
                request_parameters={}, raw_payload=[], response_metadata={}, ingestion_status="success",
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )
    state = DashboardService(SqlAlchemyDashboardRepository(session_factory), settings).system(
        datetime(2026, 9, 2, tzinfo=UTC)
    )
    assert state["system_status"] == "OPERATIONAL"
    assert state["market_status"] == "STALE"
    assert state["stale"] is True
    with session_factory.begin() as session:
        session.add(
            MarketSnapshot(
                id=uuid4(), provider_name="provider", provider_sport_key="americanfootball_ncaaf",
                canonical_league="NCAAF", requested_at=datetime(2026, 9, 2, 0, 0, 30, tzinfo=UTC),
                request_parameters={}, raw_payload=[], response_metadata={}, ingestion_status="success",
                created_at=datetime(2026, 9, 2, 0, 0, 30, tzinfo=UTC),
            )
        )
    fresh = DashboardService(SqlAlchemyDashboardRepository(session_factory), settings).system(
        datetime(2026, 9, 2, 0, 1, tzinfo=UTC)
    )
    assert fresh["market_status"] == "FRESH"
    assert fresh["stale"] is False
    with session_factory.begin() as session:
        session.add(
            MarketSnapshot(
                id=uuid4(), provider_name="provider", provider_sport_key="americanfootball_ncaaf",
                canonical_league="NCAAF", requested_at=datetime(2026, 9, 2, 0, 1, 10, tzinfo=UTC),
                request_parameters={}, raw_payload=None, response_metadata=None, ingestion_status="failed",
                error_metadata={"public_error": "Provider temporarily unavailable"},
                created_at=datetime(2026, 9, 2, 0, 1, 10, tzinfo=UTC),
            )
        )
    failed = DashboardService(SqlAlchemyDashboardRepository(session_factory), settings).system(
        datetime(2026, 9, 2, 0, 1, 20, tzinfo=UTC)
    )
    assert failed["system_status"] == "OPERATIONAL"
    assert failed["market_status"] == "ERROR"
    assert failed["last_provider_error"] == "Provider temporarily unavailable"


class StubProviderWithoutCalls:
    configured = False

    def fetch_current_odds(self, _sport: str, _markets: list[str]) -> ProviderFetchResult:
        raise AssertionError("startup must not call the market provider")
