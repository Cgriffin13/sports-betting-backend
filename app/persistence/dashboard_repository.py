from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent, MarketObservation, MarketSnapshot, Sportsbook
from app.db.model_registry_models import ModelRegistryEntry


class SqlAlchemyDashboardRepository:
    """Bounded, read-only projections for the dashboard.

    Raw market snapshot JSON is intentionally absent from every projection.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def latest_snapshot_at(self) -> datetime | None:
        with self.session_factory() as session:
            return session.scalar(
                select(func.max(MarketSnapshot.requested_at)).where(
                    MarketSnapshot.canonical_league == "NCAAF",
                    MarketSnapshot.ingestion_status.in_(("success", "partial")),
                )
            )

    def snapshot_state(self) -> dict[str, Any]:
        columns = (
            MarketSnapshot.requested_at,
            MarketSnapshot.ingestion_status,
            MarketSnapshot.error_metadata,
        )
        with self.session_factory() as session:
            latest_attempt = session.execute(
                select(*columns)
                .where(MarketSnapshot.canonical_league == "NCAAF")
                .order_by(MarketSnapshot.created_at.desc(), MarketSnapshot.id)
                .limit(1)
            ).one_or_none()
            latest_success = session.scalar(
                select(func.max(MarketSnapshot.requested_at)).where(
                    MarketSnapshot.canonical_league == "NCAAF",
                    MarketSnapshot.ingestion_status.in_(("success", "partial")),
                )
            )
        return {
            "last_success_at": latest_success,
            "last_attempt_at": latest_attempt.requested_at if latest_attempt else None,
            "last_attempt_status": latest_attempt.ingestion_status if latest_attempt else None,
            "last_error": (latest_attempt.error_metadata or {}).get("public_error") if latest_attempt else None,
        }

    def list_models(self) -> list[dict[str, Any]]:
        columns = (
            ModelRegistryEntry.model_id,
            ModelRegistryEntry.market_type,
            ModelRegistryEntry.version,
            ModelRegistryEntry.status,
            ModelRegistryEntry.model_family,
            ModelRegistryEntry.feature_set_hash,
            ModelRegistryEntry.holdout_result,
            ModelRegistryEntry.promotion_decision,
            ModelRegistryEntry.consensus_version,
            ModelRegistryEntry.vig_removal_version,
            ModelRegistryEntry.registry_entry_hash,
            ModelRegistryEntry.created_at,
        )
        with self.session_factory() as session:
            rows = session.execute(
                select(*columns)
                .where(ModelRegistryEntry.league == "NCAAF")
                .order_by(ModelRegistryEntry.status, ModelRegistryEntry.market_type, ModelRegistryEntry.model_id)
            ).all()
        return [dict(row._mapping) for row in rows]

    def market_movement(self, slate_date: date, as_of: datetime, *, limit: int = 5000) -> list[dict[str, Any]]:
        start = datetime.combine(slate_date, time.min, UTC)
        end = start + timedelta(days=1)
        statement = (
            select(
                MarketObservation.id,
                MarketObservation.snapshot_id,
                MarketObservation.observed_at,
                MarketObservation.market_type,
                MarketObservation.selection_side,
                MarketObservation.point,
                MarketObservation.american_odds,
                MarketObservation.is_stale,
                MarketSnapshot.requested_at,
                CanonicalEvent.id.label("event_id"),
                CanonicalEvent.home_team,
                CanonicalEvent.away_team,
                CanonicalEvent.scheduled_start_utc,
                Sportsbook.canonical_key.label("sportsbook"),
            )
            .join(MarketSnapshot, MarketSnapshot.id == MarketObservation.snapshot_id)
            .join(CanonicalEvent, CanonicalEvent.id == MarketObservation.event_id)
            .join(Sportsbook, Sportsbook.id == MarketObservation.sportsbook_id)
            .where(
                CanonicalEvent.league == "NCAAF",
                CanonicalEvent.scheduled_start_utc >= start,
                CanonicalEvent.scheduled_start_utc < end,
                MarketObservation.observed_at <= as_of,
                MarketObservation.ingested_at <= as_of,
                MarketSnapshot.requested_at <= as_of,
            )
            .order_by(
                CanonicalEvent.scheduled_start_utc,
                CanonicalEvent.id,
                MarketSnapshot.requested_at,
                Sportsbook.canonical_key,
                MarketObservation.market_type,
                MarketObservation.selection_side,
                MarketObservation.point_key,
            )
            .limit(limit)
        )
        with self.session_factory() as session:
            return [dict(row._mapping) for row in session.execute(statement).all()]

    def market_history(
        self,
        event_id: UUID,
        market_type: str,
        selection_side: str,
        as_of: datetime,
        *,
        limit: int = 1500,
    ) -> list[dict[str, Any]]:
        statement = (
            select(
                MarketObservation.snapshot_id,
                MarketObservation.observed_at,
                MarketObservation.market_type,
                MarketObservation.selection_side,
                MarketObservation.point,
                MarketObservation.american_odds,
                MarketObservation.is_stale,
                MarketSnapshot.requested_at,
                CanonicalEvent.id.label("event_id"),
                CanonicalEvent.home_team,
                CanonicalEvent.away_team,
                CanonicalEvent.scheduled_start_utc,
                Sportsbook.canonical_key.label("sportsbook"),
            )
            .join(MarketSnapshot, MarketSnapshot.id == MarketObservation.snapshot_id)
            .join(CanonicalEvent, CanonicalEvent.id == MarketObservation.event_id)
            .join(Sportsbook, Sportsbook.id == MarketObservation.sportsbook_id)
            .where(
                CanonicalEvent.id == event_id,
                CanonicalEvent.league == "NCAAF",
                MarketObservation.market_type == market_type,
                MarketObservation.selection_side == selection_side,
                MarketObservation.observed_at <= as_of,
                MarketObservation.ingested_at <= as_of,
                MarketSnapshot.requested_at <= as_of,
            )
            .order_by(MarketSnapshot.requested_at, Sportsbook.canonical_key, MarketObservation.id)
            .limit(limit)
        )
        with self.session_factory() as session:
            return [dict(row._mapping) for row in session.execute(statement).all()]
