from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.market_models import (
    CanonicalEvent,
    MarketObservation,
    MarketSnapshot,
    ProviderSportsbook,
    Sportsbook,
)
from app.db.session import create_session_factory
from app.config import Settings
from app.domain.identity import Principal
from app.main import create_app
from app.persistence.pricing_base import PricingObservationQuery
from app.persistence.pricing_repository import (
    SqlAlchemyPricingObservationRepository,
    build_pricing_observation_statement,
)
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.security import ApiKeyAuthenticator

BASE = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
EVENT_START = datetime(2026, 8, 29, 23, 30, tzinfo=UTC)
BOOKS = (("draftkings", "DraftKings"), ("fanduel", "FanDuel"), ("betmgm", "BetMGM"))


def pricing_query(as_of: datetime) -> PricingObservationQuery:
    return PricingObservationQuery(
        leagues=("NCAAF",),
        market_types=("moneyline", "spread", "total"),
        as_of=as_of,
        event_date=date(2026, 8, 29),
    )


def test_postgresql_pricing_sql_uses_ranked_scalar_projection_without_json_columns() -> None:
    statement = build_pricing_observation_statement(pricing_query(BASE + timedelta(hours=1)))

    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()

    assert sql.count("row_number() over") == 2
    assert "pricing_latest_states" in sql
    assert "market_observations.observed_at <=" in sql
    assert "market_observations.ingested_at <=" in sql
    assert "market_snapshots.requested_at <=" in sql
    for forbidden in (
        "raw_payload",
        "request_parameters",
        "response_metadata",
        "warning_metadata",
        "error_metadata",
        "raw_source",
        "match_provenance",
    ):
        assert forbidden not in sql


def test_many_large_repeated_snapshots_return_only_latest_state_without_orm_or_json_materialization() -> None:
    engine, factory = _database(reject_json_reads=True)
    event_id, latest_snapshot_id = _seed_history(
        factory,
        snapshot_count=80,
        raw_padding_bytes=131_072,
    )
    captured_sql: list[str] = []
    loaded_entities: list[object] = []

    def capture_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if statement.lstrip().lower().startswith("with") and "pricing_latest_states" in statement:
            captured_sql.append(statement.lower())

    def capture_entity(session: Session, instance: object) -> None:
        del session
        loaded_entities.append(instance)

    event.listen(engine, "before_cursor_execute", capture_sql)
    event.listen(Session, "loaded_as_persistent", capture_entity)
    try:
        repository = SqlAlchemyPricingObservationRepository(factory)
        first = repository.list_for_pricing(pricing_query(BASE + timedelta(hours=2)))
        second = repository.list_for_pricing(pricing_query(BASE + timedelta(hours=2)))
    finally:
        event.remove(engine, "before_cursor_execute", capture_sql)
        event.remove(Session, "loaded_as_persistent", capture_entity)

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MarketSnapshot)) == 80
        assert session.scalar(select(func.count()).select_from(MarketObservation)) == 1_440
    assert len(first) == len(second) == 18
    assert first == second
    assert {item.event_id for item in first} == {event_id}
    assert {item.snapshot_id for item in first} == {latest_snapshot_id}
    assert len(captured_sql) == 2
    assert loaded_entities == []
    for sql in captured_sql:
        assert "raw_payload" not in sql
        assert "request_parameters" not in sql
        assert "response_metadata" not in sql
        assert "warning_metadata" not in sql
        assert "error_metadata" not in sql


def test_opportunities_api_is_bounded_on_realistic_repeated_snapshot_history(tmp_path: Any) -> None:
    _, factory = _database(reject_json_reads=True)
    _, latest_snapshot_id = _seed_history(
        factory,
        snapshot_count=40,
        raw_padding_bytes=65_536,
    )
    settings = Settings(
        data_dir=tmp_path,
        database_url="sqlite+pysqlite:///:memory:",
        app_api_key="pricing-stress-test-key",
        app_owner_id="pricing-stress-owner",
        starting_bankroll=Decimal("200.00"),
    )
    application = create_app(
        settings=settings,
        repository=SqlAlchemyPortfolioRepository(factory, Decimal("200.00")),
        pricing_repository=SqlAlchemyPricingObservationRepository(factory),
        authenticator=ApiKeyAuthenticator(
            {"pricing-stress-test-key": Principal("pricing-stress-owner", "Pricing Stress Owner")}
        ),
        clock=lambda: BASE + timedelta(hours=2),
    )
    client = TestClient(application, headers={"X-API-Key": "pricing-stress-test-key"})

    first = client.post(
        "/opportunities",
        json={"leagues": ["NCAAF"], "event_date": "2026-08-29", "top_n": 10},
    )
    second = client.post(
        "/opportunities",
        json={"leagues": ["NCAAF"], "event_date": "2026-08-29", "top_n": 10},
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["observations_considered"] == 18
    assert first.json()["opportunities_returned"] == 0
    assert first.json()["opportunities"] == []
    assert {str(latest_snapshot_id)} == {
        str(item.snapshot_id)
        for item in SqlAlchemyPricingObservationRepository(factory).list_for_pricing(
            pricing_query(BASE + timedelta(hours=2))
        )
    }


def test_sql_latest_state_honors_observation_and_ingestion_cutoffs() -> None:
    _, factory = _database()
    event_id, first_snapshot_id = _seed_history(factory, snapshot_count=1, raw_padding_bytes=4_096)
    late_snapshot_id = _seed_snapshot(
        factory,
        event_id=event_id,
        observed_at=BASE,
        requested_at=BASE + timedelta(hours=3),
        ingested_at=BASE + timedelta(hours=3),
        spread_home=Decimal("-4.5"),
        raw_padding_bytes=4_096,
    )
    repository = SqlAlchemyPricingObservationRepository(factory)

    at_eleven = repository.list_for_pricing(pricing_query(BASE + timedelta(hours=1)))
    at_fourteen = repository.list_for_pricing(pricing_query(BASE + timedelta(hours=4)))

    assert {item.snapshot_id for item in at_eleven} == {first_snapshot_id}
    assert {item.point for item in at_eleven if item.market_type == "spread"} == {
        Decimal("-3.500"),
        Decimal("3.500"),
    }
    assert {item.snapshot_id for item in at_fourteen} == {late_snapshot_id}
    assert {item.point for item in at_fourteen if item.market_type == "spread"} == {
        Decimal("-4.500"),
        Decimal("4.500"),
    }


def _database(*, reject_json_reads: bool = False) -> tuple[Engine, sessionmaker[Session]]:
    def reject_json(value: str) -> Any:
        raise AssertionError(f"Pricing query unexpectedly deserialized JSON ({len(value)} bytes)")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        json_deserializer=reject_json if reject_json_reads else None,
    )
    Base.metadata.create_all(engine)
    return engine, create_session_factory(engine)


def _seed_history(
    factory: sessionmaker[Session],
    *,
    snapshot_count: int,
    raw_padding_bytes: int,
) -> tuple[UUID, UUID]:
    event_id = uuid4()
    with factory() as session, session.begin():
        session.add(
            CanonicalEvent(
                id=event_id,
                league="NCAAF",
                home_team="Coastal Tech",
                away_team="Mountain State",
                scheduled_start_utc=EVENT_START,
                event_status="scheduled",
                match_confidence=Decimal("1"),
                review_status="matched",
                match_provenance={"method": "fixture"},
                created_at=BASE,
                updated_at=BASE,
            )
        )
        _seed_books(session)
    latest_snapshot_id = uuid4()
    for index in range(snapshot_count):
        latest_snapshot_id = _seed_snapshot(
            factory,
            event_id=event_id,
            observed_at=BASE + timedelta(seconds=index),
            requested_at=BASE + timedelta(seconds=index),
            ingested_at=BASE + timedelta(seconds=index),
            spread_home=Decimal("-3.5"),
            raw_padding_bytes=raw_padding_bytes,
        )
    return event_id, latest_snapshot_id


def _seed_books(session: Session) -> None:
    for key, name in BOOKS:
        book = Sportsbook(
            id=uuid4(),
            canonical_key=key,
            display_name=name,
            active=True,
            created_at=BASE,
            updated_at=BASE,
        )
        session.add(book)
        session.flush()
        session.add(
            ProviderSportsbook(
                id=uuid4(),
                provider_name="the_odds_api",
                provider_identifier=key,
                provider_display_name=name,
                sportsbook_id=book.id,
                active=True,
                created_at=BASE,
                updated_at=BASE,
            )
        )


def _seed_snapshot(
    factory: sessionmaker[Session],
    *,
    event_id: UUID,
    observed_at: datetime,
    requested_at: datetime,
    ingested_at: datetime,
    spread_home: Decimal,
    raw_padding_bytes: int,
) -> UUID:
    snapshot_id = uuid4()
    with factory() as session, session.begin():
        snapshot = MarketSnapshot(
            id=snapshot_id,
            provider_name="the_odds_api",
            provider_sport_key="americanfootball_ncaaf",
            canonical_league="NCAAF",
            requested_at=requested_at,
            provider_retrieved_at=observed_at,
            request_parameters={"regions": "us", "markets": "h2h,spreads,totals"},
            raw_payload=_realistic_raw_payload(raw_padding_bytes),
            response_metadata={"requests_remaining": 100},
            ingestion_status="success",
            warning_metadata=None,
            error_metadata=None,
            created_at=ingested_at,
        )
        session.add(snapshot)
        session.flush()
        books = session.execute(
            select(Sportsbook.id, ProviderSportsbook.id, Sportsbook.canonical_key)
            .join(ProviderSportsbook, ProviderSportsbook.sportsbook_id == Sportsbook.id)
            .order_by(Sportsbook.canonical_key)
        ).all()
        for sportsbook_id, provider_sportsbook_id, book_key in books:
            _seed_observations(
                session,
                snapshot_id=snapshot_id,
                event_id=event_id,
                sportsbook_id=sportsbook_id,
                provider_sportsbook_id=provider_sportsbook_id,
                book_key=book_key,
                observed_at=observed_at,
                ingested_at=ingested_at,
                spread_home=spread_home,
            )
    return snapshot_id


def _seed_observations(
    session: Session,
    *,
    snapshot_id: UUID,
    event_id: UUID,
    sportsbook_id: UUID,
    provider_sportsbook_id: UUID,
    book_key: str,
    observed_at: datetime,
    ingested_at: datetime,
    spread_home: Decimal,
) -> None:
    offers = (
        ("moneyline", "home", "Coastal Tech", None),
        ("moneyline", "away", "Mountain State", None),
        ("spread", "home", "Coastal Tech", spread_home),
        ("spread", "away", "Mountain State", -spread_home),
        ("total", "over", "Over", Decimal("52.5")),
        ("total", "under", "Under", Decimal("52.5")),
    )
    for market_type, side, selection_name, point in offers:
        session.add(
            MarketObservation(
                id=uuid4(),
                snapshot_id=snapshot_id,
                event_id=event_id,
                sportsbook_id=sportsbook_id,
                provider_sportsbook_id=provider_sportsbook_id,
                market_type=market_type,
                period="full_game",
                selection_side=side,
                selection_name=selection_name,
                point=point,
                point_key="none" if point is None else format(point, ".3f"),
                american_odds=-110,
                provider_updated_at=observed_at,
                observed_at=observed_at,
                ingested_at=ingested_at,
                observation_age_seconds=max(0, int((ingested_at - observed_at).total_seconds())),
                freshness_policy_version="market-freshness-v1",
                stale_after_seconds=20_000,
                is_stale=False,
                observation_status="active",
                match_review_status="matched",
                raw_source={"book": book_key, "fixture": True},
                created_at=ingested_at,
            )
        )


def _realistic_raw_payload(padding_bytes: int) -> list[dict[str, Any]]:
    return [
        {
            "id": "ncaaf-2026-001",
            "sport_key": "americanfootball_ncaaf",
            "commence_time": "2026-08-29T23:30:00Z",
            "home_team": "Coastal Tech",
            "away_team": "Mountain State",
            "bookmakers": [
                {
                    "key": key,
                    "title": name,
                    "markets": [
                        {"key": "h2h", "outcomes": [{"price": -110}, {"price": -110}]},
                        {"key": "spreads", "outcomes": [{"point": -3.5}, {"point": 3.5}]},
                        {"key": "totals", "outcomes": [{"point": 52.5}, {"point": 52.5}]},
                    ],
                }
                for key, name in BOOKS
            ],
            "provider_extension_payload": "x" * padding_bytes,
        }
    ]
