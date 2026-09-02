from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.base import Base
from app.db.market_models import MarketObservation, MarketSnapshot
from app.db.portfolio_models import RecommendationDecisionRun
from app.main import create_app
from app.persistence.recommendation_repository import _normalize_aggregate_funnel_gauges
from app.providers.odds_api import TheOddsApiProvider


REQUEST_STARTED = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)
PROVIDER_QUOTE_AT = datetime(2026, 9, 5, 12, 0, 3, tzinfo=UTC)
PROVIDER_RESPONSE_AT = datetime(2026, 9, 5, 12, 0, 5, tzinfo=UTC)
INGESTION_COMPLETED_AT = datetime(2026, 9, 5, 12, 0, 6, tzinfo=UTC)


class DelayedProviderResponse:
    status_code = 200
    headers = {"Date": "Sat, 05 Sep 2026 12:00:05 GMT"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "elapsed-refresh-event",
                "sport_key": "americanfootball_ncaaf",
                "commence_time": "2026-09-05T19:00:00Z",
                "home_team": "Refresh Home",
                "away_team": "Refresh Away",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "last_update": PROVIDER_QUOTE_AT.isoformat(),
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": PROVIDER_QUOTE_AT.isoformat(),
                                "outcomes": [
                                    {"name": "Refresh Home", "price": 122},
                                    {"name": "Refresh Away", "price": 100},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "fanduel",
                        "title": "FanDuel",
                        "last_update": PROVIDER_QUOTE_AT.isoformat(),
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": PROVIDER_QUOTE_AT.isoformat(),
                                "outcomes": [
                                    {"name": "Refresh Home", "price": -110},
                                    {"name": "Refresh Away", "price": -110},
                                ],
                            }
                        ],
                    },
                    {
                        "key": "betmgm",
                        "title": "BetMGM",
                        "last_update": PROVIDER_QUOTE_AT.isoformat(),
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": PROVIDER_QUOTE_AT.isoformat(),
                                "outcomes": [
                                    {"name": "Refresh Home", "price": -120},
                                    {"name": "Refresh Away", "price": 100},
                                ],
                            }
                        ],
                    },
                ],
            }
        ]


def test_explicit_refresh_prices_after_new_snapshot_is_persisted(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> DelayedProviderResponse:
        requests.append({"url": url, "params": params, "timeout": timeout})
        return DelayedProviderResponse()

    settings = Settings(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'elapsed-refresh.sqlite3').as_posix()}",
        app_api_key="elapsed-refresh-test-key",
        odds_api_key="fixture-key-not-a-secret",
        starting_bankroll=Decimal("200"),
        data_dir=tmp_path,
    )
    provider = TheOddsApiProvider(
        settings.odds_api_key,
        requester=requester,
        clock=lambda: REQUEST_STARTED,
        cache_ttl_seconds=0,
    )
    application = create_app(settings=settings, provider=provider, clock=lambda: INGESTION_COMPLETED_AT)
    Base.metadata.create_all(application.state.database_engine)
    client = TestClient(application, headers={"X-API-Key": settings.app_api_key})

    with client:
        refresh = client.post("/dashboard/portfolio/paper-main/refresh-markets")
        old_cutoff = client.post(
            "/opportunities",
            json={
                "leagues": ["NCAAF"],
                "market_types": ["moneyline"],
                "event_date": "2026-09-05",
                "as_of": REQUEST_STARTED.isoformat(),
            },
        )
        completed_cutoff = client.post(
            "/opportunities",
            json={
                "leagues": ["NCAAF"],
                "market_types": ["moneyline"],
                "event_date": "2026-09-05",
                "as_of": INGESTION_COMPLETED_AT.isoformat(),
            },
        )
        watchlist = client.get("/portfolio/paper-main/watchlist?upcoming_only=true")

    assert refresh.status_code == 200, refresh.text
    assert old_cutoff.status_code == 200, old_cutoff.text
    assert completed_cutoff.status_code == 200, completed_cutoff.text
    assert watchlist.status_code == 200, watchlist.text
    assert len(requests) == 1

    result = refresh.json()
    funnel = watchlist.json()["pricing_funnel"]
    assert datetime.fromisoformat(result["requested_at"]) == REQUEST_STARTED
    assert datetime.fromisoformat(result["provider_retrieved_at"]) == PROVIDER_RESPONSE_AT
    assert datetime.fromisoformat(result["ingestion_completed_at"]) == INGESTION_COMPLETED_AT
    assert datetime.fromisoformat(result["decision_as_of"]) == INGESTION_COMPLETED_AT
    assert funnel["snapshot_age_seconds"] == 6
    assert funnel["eligible_observations"] == 6
    assert funnel["exact_paired_book_markets"] == 3
    assert funnel["calculable_candidate_sides"] == 2
    assert old_cutoff.json()["observations_considered"] == 0
    assert completed_cutoff.json()["observations_considered"] == 6
    assert {
        snapshot_id
        for item in completed_cutoff.json()["opportunities"]
        for snapshot_id in item["snapshot_ids"]
    } == {result["snapshot_id"]}

    snapshot_id = UUID(result["snapshot_id"])
    with application.state.database_engine.connect() as connection:
        snapshot = connection.execute(
            select(
                MarketSnapshot.requested_at,
                MarketSnapshot.provider_retrieved_at,
                MarketSnapshot.created_at,
            ).where(MarketSnapshot.id == snapshot_id)
        ).one()
        observations = connection.execute(
            select(MarketObservation.observed_at, MarketObservation.ingested_at).where(
                MarketObservation.snapshot_id == snapshot_id
            )
        ).all()
        decision_as_of = connection.execute(select(RecommendationDecisionRun.as_of)).scalar_one()

    assert snapshot.requested_at.replace(tzinfo=UTC) == REQUEST_STARTED
    assert snapshot.provider_retrieved_at.replace(tzinfo=UTC) == PROVIDER_RESPONSE_AT
    assert snapshot.created_at.replace(tzinfo=UTC) == INGESTION_COMPLETED_AT
    assert {row.observed_at.replace(tzinfo=UTC) for row in observations} == {PROVIDER_QUOTE_AT}
    assert {row.ingested_at.replace(tzinfo=UTC) for row in observations} == {INGESTION_COMPLETED_AT}
    assert decision_as_of.replace(tzinfo=UTC) == INGESTION_COMPLETED_AT


def test_aggregate_snapshot_age_is_latest_snapshot_gauge_not_sum_or_oldest() -> None:
    aggregate: Counter[str] = Counter({"snapshot_age_seconds": 390_272})
    samples = [
        {"snapshot_age_seconds": 390_266, "latest_observations": 100},
        {"snapshot_age_seconds": 6, "latest_observations": 100},
    ]

    _normalize_aggregate_funnel_gauges(aggregate, samples)

    assert aggregate["snapshot_age_seconds"] == 6
