from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent, MarketObservation, MarketSnapshot, ProviderSportsbook, Sportsbook
from app.config import Settings
from app.persistence.dashboard_repository import SqlAlchemyDashboardRepository
from app.services.dashboard_service import DashboardService


def test_dashboard_reads_are_authenticated_and_expose_safe_policy(
    raw_client: TestClient,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    raw_client.app.state.dashboard_service = DashboardService(  # type: ignore[attr-defined]
        SqlAlchemyDashboardRepository(session_factory), settings
    )
    assert raw_client.get("/dashboard/system").status_code == 401
    response = raw_client.get("/dashboard/system", headers={"X-API-Key": "test-primary-key"})
    assert response.status_code == 200
    body = response.json()
    assert body["paper_trading"] is True
    assert body["league"] == "NCAAF"
    assert body["policies"]["kelly_fraction"] == 0.25
    assert "app_api_key" not in body["policies"]
    assert "odds_api_key" not in body["policies"]


def test_market_movement_is_time_bounded_and_never_selects_raw_payload(
    client: TestClient,
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> None:
    event_id = uuid4()
    snapshot_id = uuid4()
    late_snapshot_id = uuid4()
    book_id = uuid4()
    provider_book_id = uuid4()
    kickoff = datetime(2026, 9, 5, 20, tzinfo=UTC)
    with session_factory.begin() as session:
        session.add(CanonicalEvent(id=event_id, league="NCAAF", home_team="Home", away_team="Away", scheduled_start_utc=kickoff, match_confidence=Decimal("1"), review_status="matched", match_provenance={}))
        session.add(Sportsbook(id=book_id, canonical_key="draftkings", display_name="DraftKings", active=True))
        session.add(ProviderSportsbook(id=provider_book_id, provider_name="the_odds_api", provider_identifier="draftkings", provider_display_name="DraftKings", sportsbook_id=book_id, active=True))
        for current_id, requested in ((snapshot_id, datetime(2026, 9, 5, 12, tzinfo=UTC)), (late_snapshot_id, datetime(2026, 9, 5, 15, tzinfo=UTC))):
            session.add(MarketSnapshot(id=current_id, provider_name="the_odds_api", provider_sport_key="americanfootball_ncaaf", canonical_league="NCAAF", requested_at=requested, request_parameters={}, raw_payload={"large": "secret-free-payload" * 100}, response_metadata={}, ingestion_status="success"))
            session.add(MarketObservation(id=uuid4(), snapshot_id=current_id, event_id=event_id, sportsbook_id=book_id, provider_sportsbook_id=provider_book_id, market_type="spread", period="full_game", selection_side="home", selection_name="Home", point=Decimal("-3.5") if current_id == snapshot_id else Decimal("-4.5"), point_key="-3.500" if current_id == snapshot_id else "-4.500", american_odds=-110, observed_at=requested, ingested_at=requested, observation_age_seconds=0, freshness_policy_version="freshness-v1", stale_after_seconds=120, is_stale=False, observation_status="active", match_review_status="matched", raw_source={}))

    statements: list[str] = []
    engine = session_factory.kw["bind"]
    def capture(_conn: object, _cursor: object, statement: str, _params: object, _context: object, _many: object) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        client.app.state.dashboard_service = DashboardService(  # type: ignore[attr-defined]
            SqlAlchemyDashboardRepository(session_factory), settings
        )
        response = client.get("/dashboard/market-movement", params={"slate_date": "2026-09-05", "as_of": "2026-09-05T13:00:00Z"})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    body = response.json()
    assert body["source_snapshot_count"] == 1
    assert body["events"][0]["points"][0]["point"] == -3.5
    movement_selects = [sql.lower() for sql in statements if "market_observations" in sql.lower()]
    assert movement_selects
    assert all("raw_payload" not in sql and "request_parameters" not in sql for sql in movement_selects)
