from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.market_models import (
    CanonicalEvent,
    MarketObservation,
    MarketSnapshot,
    ProviderEventMapping,
    ProviderSportsbook,
    Sportsbook,
)
from app.main import create_app
from app.persistence.market_repository import SqlAlchemyMarketDataRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import MarketDataProviderError, MarketGame, MarketOffer, ProviderFetchResult
from app.providers.odds_api import TheOddsApiProvider
from app.security import ApiKeyAuthenticator
from app.services.market_ingestion_service import MarketIngestionService


class FixtureResponse:
    status_code = 200

    def __init__(self, payload: list[Any]) -> None:
        self._payload = payload
        self.headers = {
            "Date": "Sat, 29 Aug 2026 20:00:30 GMT",
            "x-requests-remaining": "100",
            "x-requests-used": "20",
        }

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[Any]:
        return self._payload


class StaticFetchProvider:
    configured = True

    def __init__(self, fetch: ProviderFetchResult) -> None:
        self.fetch = fetch

    def fetch_current_odds(self, sport: str, markets: list[str]) -> ProviderFetchResult:
        return self.fetch


@pytest.fixture
def ncaaf_payload() -> list[Any]:
    path = Path(__file__).parent / "fixtures" / "ncaaf_odds.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


def parse_fixture(payload: list[Any], *, requested_at: datetime | None = None) -> ProviderFetchResult:
    clock_value = requested_at or datetime(2026, 8, 29, 20, 0, 31, tzinfo=UTC)
    provider = TheOddsApiProvider(
        "fixture-key",
        requester=lambda url, *, params, timeout: FixtureResponse(payload),
        cache_ttl_seconds=0,
        clock=lambda: clock_value,
    )
    return provider.fetch_current_odds("NCAAF", ["h2h", "spreads", "totals"])


def repository_at(
    session_factory: sessionmaker[Session],
    now: datetime,
    *,
    freshness_seconds: int = 120,
) -> SqlAlchemyMarketDataRepository:
    return SqlAlchemyMarketDataRepository(
        session_factory,
        freshness_seconds=freshness_seconds,
        clock=lambda: now,
    )


def test_realistic_ncaaf_snapshot_persists_raw_events_books_and_all_markets(
    ncaaf_payload: list[Any],
    session_factory: sessionmaker[Session],
) -> None:
    fetch = parse_fixture(ncaaf_payload)
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, 40, tzinfo=UTC))

    result = repository.persist_fetch(fetch)

    assert result.events_created == 1
    assert result.observations_created == 18
    assert result.warnings == ()
    with session_factory() as session:
        snapshot = session.get(MarketSnapshot, result.snapshot_id)
        assert snapshot is not None
        assert snapshot.provider_name == "the_odds_api"
        assert snapshot.provider_sport_key == "americanfootball_ncaaf"
        assert snapshot.canonical_league == "NCAAF"
        assert snapshot.raw_payload == ncaaf_payload
        assert "apiKey" not in snapshot.request_parameters
        assert snapshot.response_metadata == {
            "requests_remaining": 100,
            "requests_used": 20,
            "cache": "miss",
        }
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ProviderEventMapping)) == 1
        assert session.scalar(select(func.count()).select_from(Sportsbook)) == 3
        assert session.scalar(select(func.count()).select_from(ProviderSportsbook)) == 3
        observations = list(session.scalars(select(MarketObservation)))
        assert {item.market_type for item in observations} == {"moneyline", "spread", "total"}
        assert {item.period for item in observations} == {"full_game"}
        assert {item.selection_side for item in observations} == {"home", "away", "over", "under"}
        assert {float(item.point or 0) for item in observations if item.market_type == "spread"} == {
            -4.0,
            -3.5,
            3.5,
            4.0,
        }
        assert {float(item.point or 0) for item in observations if item.market_type == "total"} == {52.5, 53.0}
        assert all(item.is_stale is False for item in observations)
        assert all(item.raw_source["provider_event_id"] == "ncaaf-2026-001" for item in observations)


def test_repeat_ingestion_reuses_event_and_preserves_line_movement_across_snapshots(
    ncaaf_payload: list[Any],
    session_factory: sessionmaker[Session],
) -> None:
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 2, tzinfo=UTC), freshness_seconds=300)
    first = repository.persist_fetch(parse_fixture(ncaaf_payload))
    moved_payload = copy.deepcopy(ncaaf_payload)
    draftkings = moved_payload[0]["bookmakers"][0]
    draftkings["last_update"] = "2026-08-29T20:01:30Z"
    draftkings["markets"][1]["last_update"] = "2026-08-29T20:01:30Z"
    draftkings["markets"][1]["outcomes"][0].update({"point": -4.5, "price": -105})
    draftkings["markets"][1]["outcomes"][1].update({"point": 4.5, "price": -115})
    second = repository.persist_fetch(
        parse_fixture(moved_payload, requested_at=datetime(2026, 8, 29, 20, 1, 31, tzinfo=UTC))
    )

    assert first.snapshot_id != second.snapshot_id
    assert second.events_created == 0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MarketSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ProviderEventMapping)) == 1
        assert session.scalar(select(func.count()).select_from(MarketObservation)) == 36
        draftkings_id = session.scalar(select(Sportsbook.id).where(Sportsbook.canonical_key == "draftkings"))
        home_spreads = list(
            session.scalars(
                select(MarketObservation)
                .where(
                    MarketObservation.sportsbook_id == draftkings_id,
                    MarketObservation.market_type == "spread",
                    MarketObservation.selection_side == "home",
                )
                .order_by(MarketObservation.observed_at)
            )
        )
        assert [(float(item.point or 0), item.american_odds) for item in home_spreads] == [
            (-3.5, -110),
            (-4.5, -105),
        ]


def test_conflicting_provider_event_id_creates_reviewable_candidate_without_silent_merge(
    session_factory: sessionmaker[Session],
) -> None:
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, tzinfo=UTC))
    first = fetch_for_game("NCAAF", "americanfootball_ncaaf", "shared-id", "Home A", "Away A")
    conflict = fetch_for_game("NCAAF", "americanfootball_ncaaf", "shared-id", "Home B", "Away B")

    repository.persist_fetch(first)
    repository.persist_fetch(conflict)
    repository.persist_fetch(conflict)

    with session_factory() as session:
        events = list(session.scalars(select(CanonicalEvent).order_by(CanonicalEvent.home_team)))
        mappings = list(session.scalars(select(ProviderEventMapping)))
        assert len(events) == len(mappings) == 2
        assert {item.home_team for item in events} == {"Home A", "Home B"}
        assert {item.review_status for item in events} == {"conflict"}
        assert {item.match_confidence for item in events} == {0}


def test_missing_provider_id_is_not_silently_matched_and_observations_are_reviewable(
    session_factory: sessionmaker[Session],
) -> None:
    offer = MarketOffer("DraftKings", "h2h", "Home A", -120, book_key="draftkings")
    fetch = fetch_for_game("NCAAF", "americanfootball_ncaaf", None, "Home A", "Away A", offers=(offer,))
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, tzinfo=UTC))

    repository.persist_fetch(fetch)
    repository.persist_fetch(fetch)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 2
        assert session.scalar(select(func.count()).select_from(ProviderEventMapping)) == 0
        assert set(session.scalars(select(MarketObservation.match_review_status))) == {"needs_review"}


def test_duplicate_observation_within_snapshot_is_skipped(
    session_factory: sessionmaker[Session],
) -> None:
    offer = MarketOffer("DraftKings", "spreads", "Home A", -110, -3.5, True, "draftkings")
    fetch = fetch_for_game(
        "NCAAF",
        "americanfootball_ncaaf",
        "duplicate-id",
        "Home A",
        "Away A",
        offers=(offer, offer),
    )
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, tzinfo=UTC))

    result = repository.persist_fetch(fetch)

    assert result.observations_created == 1
    assert any(warning["code"] == "duplicate_observation_skipped" for warning in result.warnings)


def test_freshness_fields_are_versioned_and_stale_is_identifiable(
    session_factory: sessionmaker[Session],
) -> None:
    provider_time = datetime(2026, 8, 29, 19, 55, tzinfo=UTC)
    offer = MarketOffer(
        "DraftKings",
        "totals",
        "Over",
        -110,
        52.5,
        True,
        "draftkings",
        provider_time,
    )
    fetch = fetch_for_game(
        "NCAAF", "americanfootball_ncaaf", "stale-id", "Home A", "Away A", offers=(offer,)
    )
    repository = repository_at(
        session_factory,
        datetime(2026, 8, 29, 20, 0, tzinfo=UTC),
        freshness_seconds=120,
    )

    repository.persist_fetch(fetch)

    with session_factory() as session:
        observation = session.scalar(select(MarketObservation))
        assert observation is not None
        assert observation.observation_age_seconds == 300
        assert observation.stale_after_seconds == 120
        assert observation.freshness_policy_version == "market-freshness-v1"
        assert observation.is_stale is True


def test_transaction_rolls_back_raw_and_normalized_rows_when_observation_insert_fails(
    ncaaf_payload: list[Any],
    session_factory: sessionmaker[Session],
) -> None:
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, 40, tzinfo=UTC))

    def fail_observation(session: Session, *_: Any) -> None:
        if any(isinstance(item, MarketObservation) for item in session.new):
            raise RuntimeError("injected observation failure")

    event.listen(Session, "before_flush", fail_observation)
    try:
        with pytest.raises(RuntimeError, match="injected observation failure"):
            repository.persist_fetch(parse_fixture(ncaaf_payload))
    finally:
        event.remove(Session, "before_flush", fail_observation)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MarketSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(MarketObservation)) == 0


def test_malformed_provider_data_is_preserved_with_structured_warning(
    session_factory: sessionmaker[Session],
) -> None:
    payload: list[Any] = ["not-an-event", {"id": "missing-fields", "bookmakers": "invalid"}]
    fetch = parse_fixture(payload)
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 1, tzinfo=UTC))

    result = repository.persist_fetch(fetch)

    assert result.observations_created == 0
    with session_factory() as session:
        snapshot = session.get(MarketSnapshot, result.snapshot_id)
        assert snapshot is not None
        assert snapshot.raw_payload == payload
        assert snapshot.ingestion_status == "partial"
        assert {warning["code"] for warning in snapshot.warning_metadata or []} >= {
            "malformed_event",
            "malformed_bookmakers",
            "event_not_normalized",
        }


def test_sanitized_provider_failure_is_persisted_without_credentials(
    session_factory: sessionmaker[Session],
) -> None:
    secret = "never-persist-this"

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FixtureResponse:
        raise requests.ConnectionError(f"{url}?apiKey={secret}")

    provider = TheOddsApiProvider(secret, requester=requester, max_retries=0)
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 1, tzinfo=UTC))

    with pytest.raises(MarketDataProviderError, match="Provider request failed"):
        MarketIngestionService(provider, repository).ingest("NCAAF", ["h2h"])

    with session_factory() as session:
        snapshot = session.scalar(select(MarketSnapshot))
        assert snapshot is not None
        assert snapshot.ingestion_status == "failed"
        assert snapshot.raw_payload is None
        assert snapshot.error_metadata == {"public_error": "Provider request failed"}
        serialized = json.dumps(
            {
                "request": snapshot.request_parameters,
                "error": snapshot.error_metadata,
            }
        )
        assert secret not in serialized
        assert "apiKey" not in serialized


def test_ncaaf_and_ncaab_remain_distinct_even_if_provider_ids_collide(
    session_factory: sessionmaker[Session],
) -> None:
    repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, tzinfo=UTC))
    repository.persist_fetch(fetch_for_game("NCAAF", "americanfootball_ncaaf", "same-id", "A", "B"))
    repository.persist_fetch(fetch_for_game("NCAAB", "basketball_ncaab", "same-id", "A", "B"))

    with session_factory() as session:
        assert set(session.scalars(select(CanonicalEvent.league))) == {"NCAAF", "NCAAB"}
        assert set(session.scalars(select(ProviderEventMapping.provider_sport_key))) == {
            "americanfootball_ncaaf",
            "basketball_ncaab",
        }


def test_odds_api_response_remains_flattened_and_exposes_persisted_snapshot_id(
    ncaaf_payload: list[Any],
    settings: Settings,
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
    authenticator: ApiKeyAuthenticator,
) -> None:
    fetch = parse_fixture(ncaaf_payload)
    market_repository = repository_at(session_factory, datetime(2026, 8, 29, 20, 0, 40, tzinfo=UTC))
    application = create_app(
        settings=settings,
        provider=StaticFetchProvider(fetch),
        repository=repository,
        market_repository=market_repository,
        authenticator=authenticator,
    )
    client = TestClient(application, headers={"X-API-Key": "test-primary-key"})

    response = client.post(
        "/odds",
        json={"date": "2026-08-29", "sports": ["NCAAF"], "markets": ["h2h", "spreads", "totals"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == body["snapshot_ids"]["NCAAF"]
    assert body["games"][0]["game_id"] == "ncaaf-2026-001"
    assert {offer["market_type"] for offer in body["games"][0]["offers"]} == {"h2h", "spreads", "totals"}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MarketSnapshot)) == 1


def fetch_for_game(
    league: str,
    provider_sport_key: str,
    provider_event_id: str | None,
    home_team: str,
    away_team: str,
    *,
    offers: tuple[MarketOffer, ...] = (),
) -> ProviderFetchResult:
    requested_at = datetime(2026, 8, 29, 19, 59, tzinfo=UTC)
    return ProviderFetchResult(
        provider_name="the_odds_api",
        provider_sport_key=provider_sport_key,
        canonical_league=league,
        requested_at=requested_at,
        provider_retrieved_at=requested_at,
        request_parameters={"regions": "us", "markets": "h2h,spreads,totals", "oddsFormat": "american"},
        raw_payload=[],
        response_metadata={},
        warnings=(),
        games=(
            MarketGame(
                provider_event_id,
                league,
                home_team,
                away_team,
                "2026-08-30T00:00:00Z",
                offers,
            ),
        ),
    )
