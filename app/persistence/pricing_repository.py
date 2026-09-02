from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent, MarketObservation, MarketSnapshot, Sportsbook
from app.domain.pricing import PricingObservation
from app.persistence.pricing_base import PricingObservationQuery


class SqlAlchemyPricingObservationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_for_pricing(self, query: PricingObservationQuery) -> tuple[PricingObservation, ...]:
        statement = build_pricing_observation_statement(query)
        with self._session_factory() as session:
            rows = session.execute(statement).mappings()
            return tuple(_to_domain(row) for row in rows)


def build_pricing_observation_statement(query: PricingObservationQuery) -> Select[Any]:
    """Select only the latest time-eligible normalized market state and required scalar columns."""
    cutoff = _as_utc(query.as_of)
    event_start, event_end = _event_bounds(query)
    candidate_conditions = [
        CanonicalEvent.league.in_(query.leagues),
        MarketObservation.market_type.in_(query.market_types),
        MarketObservation.observed_at <= cutoff,
        MarketObservation.ingested_at <= cutoff,
        MarketSnapshot.requested_at <= cutoff,
    ]
    if event_start is not None and event_end is not None:
        candidate_conditions.extend(
            (
                CanonicalEvent.scheduled_start_utc >= event_start,
                CanonicalEvent.scheduled_start_utc < event_end,
            )
        )

    candidate_rows = (
        select(
            MarketObservation.event_id.label("event_id"),
            MarketObservation.sportsbook_id.label("sportsbook_id"),
            MarketObservation.market_type.label("market_type"),
            MarketObservation.period.label("period"),
            MarketObservation.snapshot_id.label("snapshot_id"),
            MarketObservation.observed_at.label("state_observed_at"),
            MarketObservation.ingested_at.label("state_ingested_at"),
            MarketSnapshot.requested_at.label("snapshot_requested_at"),
            func.row_number()
            .over(
                partition_by=(
                    MarketObservation.event_id,
                    MarketObservation.sportsbook_id,
                    MarketObservation.market_type,
                    MarketObservation.period,
                    MarketObservation.snapshot_id,
                ),
                order_by=(
                    MarketSnapshot.requested_at.desc(),
                    MarketObservation.observed_at.desc(),
                    MarketObservation.ingested_at.desc(),
                    MarketObservation.snapshot_id.desc(),
                    MarketObservation.id.desc(),
                ),
            )
            .label("snapshot_row_rank"),
        )
        .join(CanonicalEvent, CanonicalEvent.id == MarketObservation.event_id)
        .join(MarketSnapshot, MarketSnapshot.id == MarketObservation.snapshot_id)
        .where(*candidate_conditions)
        .cte("pricing_candidate_rows")
    )
    snapshot_heads = (
        select(
            candidate_rows.c.event_id,
            candidate_rows.c.sportsbook_id,
            candidate_rows.c.market_type,
            candidate_rows.c.period,
            candidate_rows.c.snapshot_id,
            candidate_rows.c.state_observed_at,
            candidate_rows.c.state_ingested_at,
            candidate_rows.c.snapshot_requested_at,
        )
        .where(candidate_rows.c.snapshot_row_rank == 1)
        .cte("pricing_snapshot_heads")
    )
    ranked_states = (
        select(
            snapshot_heads,
            func.row_number()
            .over(
                partition_by=(
                    snapshot_heads.c.event_id,
                    snapshot_heads.c.sportsbook_id,
                    snapshot_heads.c.market_type,
                    snapshot_heads.c.period,
                ),
                order_by=(
                    snapshot_heads.c.snapshot_requested_at.desc(),
                    snapshot_heads.c.state_observed_at.desc(),
                    snapshot_heads.c.state_ingested_at.desc(),
                    snapshot_heads.c.snapshot_id.desc(),
                ),
            )
            .label("state_rank"),
        )
        .cte("pricing_ranked_states")
    )
    latest_states = (
        select(
            ranked_states.c.event_id,
            ranked_states.c.sportsbook_id,
            ranked_states.c.market_type,
            ranked_states.c.period,
            ranked_states.c.snapshot_id,
            ranked_states.c.snapshot_requested_at,
        )
        .where(ranked_states.c.state_rank == 1)
        .cte("pricing_latest_states")
    )

    statement = (
        select(
            MarketObservation.id.label("observation_id"),
            MarketObservation.snapshot_id.label("snapshot_id"),
            MarketObservation.event_id.label("event_id"),
            CanonicalEvent.league.label("league"),
            CanonicalEvent.home_team.label("home_team"),
            CanonicalEvent.away_team.label("away_team"),
            CanonicalEvent.scheduled_start_utc.label("scheduled_start_utc"),
            CanonicalEvent.review_status.label("event_review_status"),
            MarketObservation.sportsbook_id.label("sportsbook_id"),
            Sportsbook.canonical_key.label("sportsbook_key"),
            Sportsbook.display_name.label("sportsbook_name"),
            Sportsbook.active.label("sportsbook_active"),
            MarketObservation.market_type.label("market_type"),
            MarketObservation.period.label("period"),
            MarketObservation.selection_side.label("selection_side"),
            MarketObservation.selection_name.label("selection_name"),
            MarketObservation.point.label("point"),
            MarketObservation.american_odds.label("american_odds"),
            latest_states.c.snapshot_requested_at.label("snapshot_requested_at"),
            MarketObservation.observed_at.label("observed_at"),
            MarketObservation.ingested_at.label("ingested_at"),
            MarketObservation.stale_after_seconds.label("stale_after_seconds"),
            MarketObservation.observation_status.label("observation_status"),
            MarketObservation.match_review_status.label("match_review_status"),
        )
        .join(
            latest_states,
            and_(
                latest_states.c.event_id == MarketObservation.event_id,
                latest_states.c.sportsbook_id == MarketObservation.sportsbook_id,
                latest_states.c.market_type == MarketObservation.market_type,
                latest_states.c.period == MarketObservation.period,
                latest_states.c.snapshot_id == MarketObservation.snapshot_id,
            ),
        )
        .join(CanonicalEvent, CanonicalEvent.id == MarketObservation.event_id)
        .join(Sportsbook, Sportsbook.id == MarketObservation.sportsbook_id)
        .where(
            CanonicalEvent.league.in_(query.leagues),
            MarketObservation.market_type.in_(query.market_types),
            MarketObservation.observed_at <= cutoff,
            MarketObservation.ingested_at <= cutoff,
            latest_states.c.snapshot_requested_at <= cutoff,
        )
        .order_by(
            CanonicalEvent.league,
            CanonicalEvent.scheduled_start_utc,
            MarketObservation.event_id,
            MarketObservation.sportsbook_id,
            MarketObservation.market_type,
            MarketObservation.period,
            MarketObservation.snapshot_id,
            MarketObservation.selection_side,
            MarketObservation.point,
            MarketObservation.id,
        )
    )
    if event_start is not None and event_end is not None:
        statement = statement.where(
            CanonicalEvent.scheduled_start_utc >= event_start,
            CanonicalEvent.scheduled_start_utc < event_end,
        )
    return statement


def _event_bounds(query: PricingObservationQuery) -> tuple[datetime | None, datetime | None]:
    if query.event_date is None:
        return None, None
    start = datetime.combine(query.event_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _to_domain(row: RowMapping) -> PricingObservation:
    return PricingObservation(
        observation_id=row["observation_id"],
        snapshot_id=row["snapshot_id"],
        event_id=row["event_id"],
        league=row["league"],
        home_team=row["home_team"],
        away_team=row["away_team"],
        scheduled_start_utc=_as_utc(row["scheduled_start_utc"]),
        event_review_status=row["event_review_status"],
        sportsbook_id=row["sportsbook_id"],
        sportsbook_key=row["sportsbook_key"],
        sportsbook_name=row["sportsbook_name"],
        sportsbook_active=row["sportsbook_active"],
        market_type=row["market_type"],
        period=row["period"],
        selection_side=row["selection_side"],
        selection_name=row["selection_name"],
        point=row["point"],
        american_odds=row["american_odds"],
        snapshot_requested_at=_as_utc(row["snapshot_requested_at"]),
        observed_at=_as_utc(row["observed_at"]),
        ingested_at=_as_utc(row["ingested_at"]),
        stale_after_seconds=row["stale_after_seconds"],
        observation_status=row["observation_status"],
        match_review_status=row["match_review_status"],
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
