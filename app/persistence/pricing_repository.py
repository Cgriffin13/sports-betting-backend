from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent, MarketObservation, MarketSnapshot, Sportsbook
from app.domain.pricing import PricingObservation
from app.persistence.pricing_base import PricingObservationQuery


class SqlAlchemyPricingObservationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_for_pricing(self, query: PricingObservationQuery) -> tuple[PricingObservation, ...]:
        cutoff = _as_utc(query.as_of)
        statement = (
            select(MarketObservation, CanonicalEvent, Sportsbook, MarketSnapshot)
            .join(CanonicalEvent, CanonicalEvent.id == MarketObservation.event_id)
            .join(Sportsbook, Sportsbook.id == MarketObservation.sportsbook_id)
            .join(MarketSnapshot, MarketSnapshot.id == MarketObservation.snapshot_id)
            .where(
                CanonicalEvent.league.in_(query.leagues),
                MarketObservation.market_type.in_(query.market_types),
                MarketObservation.observed_at <= cutoff,
                MarketObservation.ingested_at <= cutoff,
            )
            .order_by(
                CanonicalEvent.league,
                CanonicalEvent.scheduled_start_utc,
                MarketObservation.event_id,
                MarketObservation.sportsbook_id,
                MarketObservation.market_type,
                MarketObservation.observed_at,
                MarketObservation.ingested_at,
                MarketObservation.id,
            )
        )
        if query.event_date is not None:
            start = datetime.combine(query.event_date, time.min, tzinfo=UTC)
            statement = statement.where(
                CanonicalEvent.scheduled_start_utc >= start,
                CanonicalEvent.scheduled_start_utc < start + timedelta(days=1),
            )

        with self._session_factory() as session:
            rows = session.execute(statement).all()
            return tuple(_to_domain(observation, event, book, snapshot) for observation, event, book, snapshot in rows)


def _to_domain(
    observation: MarketObservation,
    event: CanonicalEvent,
    book: Sportsbook,
    snapshot: MarketSnapshot,
) -> PricingObservation:
    return PricingObservation(
        observation_id=observation.id,
        snapshot_id=observation.snapshot_id,
        event_id=event.id,
        league=event.league,
        home_team=event.home_team,
        away_team=event.away_team,
        scheduled_start_utc=_as_utc(event.scheduled_start_utc),
        event_review_status=event.review_status,
        sportsbook_id=book.id,
        sportsbook_key=book.canonical_key,
        sportsbook_name=book.display_name,
        sportsbook_active=book.active,
        market_type=observation.market_type,
        period=observation.period,
        selection_side=observation.selection_side,
        selection_name=observation.selection_name,
        point=observation.point,
        american_odds=observation.american_odds,
        snapshot_requested_at=_as_utc(snapshot.requested_at),
        observed_at=_as_utc(observation.observed_at),
        ingested_at=_as_utc(observation.ingested_at),
        stale_after_seconds=observation.stale_after_seconds,
        observation_status=observation.observation_status,
        match_review_status=observation.match_review_status,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
